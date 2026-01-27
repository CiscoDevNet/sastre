"""
 Sastre - Cisco-SDWAN Automation Toolset

 cisco_sdwan.base.rest_api
 This module implements the lower level REST API
"""
import json
import requests
import functools
import logging
from urllib3 import disable_warnings
from urllib3.exceptions import InsecureRequestWarning
from time import time, sleep
from typing import Any
from collections.abc import Mapping
from random import uniform


MAX_RETRIES = 10


def backoff_wait_secs(retry_count: int, ceiling: int = 5, variance: float = 0.25) -> float:
    """
    Calculates the exponential backoff time in seconds
    @param retry_count: Integer greater than or equal to 0
    @param ceiling: Defines a ceiling for the backoff time
    @param variance: Apply a random +/- variance percentage to the backoff time to avoid synchronization
    @return: Backoff time in seconds
    """
    return (1 << min(retry_count, ceiling)) * (1 + uniform(-variance, variance)) / 5


def backoff_retry(fn):
    @functools.wraps(fn)
    def retry_fn(*args, **kwargs):
        for retry in range(MAX_RETRIES):
            try:
                return fn(*args, **kwargs)
            except ServerRateLimitException as ex:
                wait_secs = backoff_wait_secs(retry)
                logging.getLogger(__name__).debug(f'{ex}: Retry {retry+1}/{MAX_RETRIES}, backoff {wait_secs:.3}s')
                sleep(wait_secs)

        raise RestAPIException(f'Maximum retries exceeded ({MAX_RETRIES})')

    return retry_fn


class Rest:
    def __init__(self, base_url: str, username: str | None, password: str | None, apikey: str | None = None,
                 tenant_name: str | None = None, timeout: int = 20, verify: bool = False):
        self.base_url = base_url
        self.timeout = timeout
        self.verify = verify
        self.session = None
        self.server_facts = None
        self.is_tenant_scope = False
        # If username and password are provided use standard login. Otherwise, use API key login
        self.use_apikey = apikey and not all((username, password))

        if not verify:
            disable_warnings(InsecureRequestWarning)

        if not self.login(username, password, apikey=apikey, tenant_name=tenant_name):
            raise LoginFailedException(
                f'Login to {self.base_url} failed, check {"API key" if self.use_apikey else "credentials"}'
            )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.session is not None:
            self.logout()
            self.session.close()

        return False

    def login_apikey(self, apikey: str) -> bool:
        logging.getLogger(__name__).debug('Using API key to authenticate with SD-WAN Manager')

        session = requests.Session()
        session.headers.update({
            "Authorization": f"Bearer {apikey}",
            'Content-Type': 'application/json'
        })
        response = session.get(f'{self.base_url}/dataservice/client/server', timeout=self.timeout, verify=self.verify)
        if response.status_code == 401:
            return False

        response.raise_for_status()

        self.session = session
        self.server_facts = response.json().get('data')

        return True

    def login_standard(self, username: str, password: str) -> bool:
        logging.getLogger(__name__).debug('Using username/password credentials to authenticate with SD-WAN Manager')

        session = requests.Session()
        auth_data = {
            'j_username': username,
            'j_password': password
        }
        response = session.post(f'{self.base_url}/j_security_check',
                                data=auth_data, timeout=self.timeout, verify=self.verify)
        response.raise_for_status()

        if b'<html>' in response.content:
            return False

        self.session = session
        self.session.headers['Content-Type'] = 'application/json'
        self.server_facts = self.get('client/server').get('data')

        return True

    def login(self, username: str | None, password: str | None, apikey: str | None, tenant_name: str | None) -> bool:
        if not (self.login_apikey(apikey) if self.use_apikey else self.login_standard(username, password)):
            return False

        if self.server_facts is None:
            raise RestAPIException('Could not retrieve SD-WAN Manager server information')
        # Token mechanism introduced in 19.2
        token = self.server_facts.get('CSRFToken')
        if token is not None:
            self.session.headers['X-XSRF-TOKEN'] = token

        # Multi-tenant vManage with a provider account, insert vsessionid
        if tenant_name is not None:
            if not self.is_multi_tenant or not self.is_provider:
                raise BadTenantException('Tenant is only applicable to provider accounts in multi-tenant deployments')

            tenant_list = self.get('tenant').get('data')
            if tenant_list is None:
                raise RestAPIException('Could not retrieve SD-WAN Manager tenant list')

            for tenant in tenant_list:
                if tenant_name == tenant['name']:
                    session_id = self.post({}, 'tenant', tenant['tenantId'], 'vsessionid').get('VSessionId')
                    self.session.headers['VSessionId'] = session_id
                    self.is_tenant_scope = True
                    break
            else:
                raise BadTenantException(f'Invalid tenant: {tenant_name}')

        return True

    def logout(self) -> bool:
        if is_version_newer('20.11', self.server_version):
            response = self.session.post(f'{self.base_url}/logout', verify=self.verify, allow_redirects=False)
        else:
            response = self.session.get(f'{self.base_url}/logout', params={'nocache': str(int(time()))},
                                        verify=self.verify, allow_redirects=False)

        return response.status_code == requests.codes.found

    @property
    def server_version(self) -> str:
        return self.server_facts.get('platformVersion', '0.0')

    @property
    def is_multi_tenant(self) -> bool:
        return self.server_facts.get('tenancyMode', '') == 'MultiTenant'

    @property
    def is_provider(self) -> bool:
        return self.server_facts.get('userMode', '') == 'provider'

    @backoff_retry
    def get(self, *path_entries: str, **params: str | int) -> dict[str, Any]:
        response = self.session.get(self._url(*path_entries),
                                    params=params if params else None,
                                    timeout=self.timeout, verify=self.verify)
        raise_for_status(response)
        return response.json()

    @backoff_retry
    def post(self, input_data: Mapping[str, Any], *path_entries: str) -> dict[str, Any] | None:
        # With large input_data, vManage fails the post request if payload is encoded in compact form. Thus encoding
        # with indent=1.
        response = self.session.post(self._url(*path_entries), data=json.dumps(input_data, indent=1),
                                     timeout=self.timeout, verify=self.verify)
        raise_for_status(response)

        # POST may return an empty string, return None in this case
        return response.json() if response.text else None

    @backoff_retry
    def put(self, input_data: Mapping[str, Any], *path_entries: str) -> dict[str, Any] | None:
        # With large input_data, vManage fails the put request if payload is encoded in compact form. Thus encoding
        # with indent=1.
        response = self.session.put(self._url(*path_entries), data=json.dumps(input_data, indent=1),
                                    timeout=self.timeout, verify=self.verify)
        raise_for_status(response)

        # PUT may return an empty string, return None in this case
        return response.json() if response.text else None

    @backoff_retry
    def delete(self, *path_entries: str, input_data: Mapping[str, Any] | None = None,
               **params: str) -> dict[str, Any] | None:
        response = self.session.delete(self._url(*path_entries),
                                       data=json.dumps(input_data, indent=1) if input_data is not None else None,
                                       params=params if params else None,
                                       timeout=self.timeout, verify=self.verify)
        raise_for_status(response)

        # DELETE normally returns an empty string, return None in this case
        return response.json() if response.text else None

    def _url(self, *path_entries: str) -> str:
        path = '/'.join(path.strip('/') for path in path_entries)

        return f'{self.base_url}/dataservice/{path}'


def raise_for_status(response):
    if response.status_code != requests.codes.ok:
        if response.status_code in {429, 503}:
            raise ServerRateLimitException(f'Received rate-limit signal (status-code {response.status_code})')

        try:
            reply_data = response.json() if response.text else {}
        except json.decoder.JSONDecodeError:
            reply_data = {'error': {'message': 'Check user permissions'}} if response.status_code == 403 else {}

        details = reply_data.get("error", {}).get("details", "")
        raise RestAPIException(f'{response.reason} ({response.status_code}): '
                               f'{reply_data.get("error", {}).get("message", "Unspecified error message")}'
                               f'{": " if details else ""}{details} [{response.request.method} {response.url}]')


def is_version_newer(version_1: str, version_2: str) -> bool:
    """
    Indicates whether one vManage version is newer than another. Compares only the first 2 digits from version
    because maintenance (i.e. 3rd digit) differences are not likely to create any incompatibility between REST API JSON
    payloads, thus not relevant in this context.

    Versions should be strings with fields separated by dots in format: <main>.<minor>.<maintenance>

    @param version_1: String containing first version
    @param version_2: String containing second version
    @return: True if version_2 is newer than version_1.
    """
    def parse(version_string: str) -> list[int]:
        # Development versions may follow this format: '20.1.999-98' or '20.9.0.02-li'
        return [int(v) for v in f"{version_string}.0".split('.')[:2]]

    return parse(version_2) > parse(version_1)


def response_id(response_payload: Mapping[str, str]) -> str:
    """
    Extracts the first value in a response payload. Assumes that this first value contains the ID of the object
    just created by the post request.
    @param response_payload: JSON response payload
    @return: The object id
    """
    if response_payload is not None:
        for value in response_payload.values():
            return value

    raise RestAPIException("Unexpected response payload")


class RestAPIException(Exception):
    """ Exception for REST API errors """
    pass


class LoginFailedException(RestAPIException):
    """ Login failure """
    pass


class BadTenantException(RestAPIException):
    """ Provided tenant is invalid or not applicable """
    pass


class ServerRateLimitException(RestAPIException):
    """ REST API server is rate limiting the request via 429 status code """
    pass
