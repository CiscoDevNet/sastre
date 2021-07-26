"""
 Sastre - Automation Tools for Cisco SD-WAN Powered by Viptela

 cisco_sdwan.base.rest_api
 This module implements the lower level REST API
"""
import requests
import urllib3
import json
from time import time
from typing import Optional


class Rest:
    def __init__(self, base_url: str, username: str, password: str, tenant_name: Optional[str] = None,
                 timeout: int = 20, verify: bool = False):
        self.base_url = base_url
        self.timeout = timeout
        self.verify = verify
        self.session = None
        self.server_facts = None
        self.is_tenant_scope = False

        if not verify:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        if not self.login(username, password, tenant_name):
            raise LoginFailedException(f'Login to {self.base_url} failed, check credentials')

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.session is not None:
            # In 19.3, logging out actually de-authorize all sessions a user may have from the same IP address. For
            # instance browser windows open from the same laptop. This is fixed in 20.1.
            self.logout()
            self.session.close()

        return False

    def login(self, username: str, password: str, tenant_name: Optional[str]) -> bool:
        data = {
            'j_username': username,
            'j_password': password
        }

        session = requests.Session()
        response = session.post(f'{self.base_url}/j_security_check',
                                data=data, timeout=self.timeout, verify=self.verify)
        response.raise_for_status()

        if b'<html>' in response.content:
            return False

        self.session = session

        self.server_facts = self.get('client/server').get('data')
        if self.server_facts is None:
            raise RestAPIException('Could not retrieve vManage server information')

        # Token mechanism introduced in 19.2
        token = self.server_facts.get('CSRFToken')
        if token is not None:
            self.session.headers['X-XSRF-TOKEN'] = token

        self.session.headers['Content-Type'] = 'application/json'

        # Multi-tenant vManage with a provider account, insert vsessionid
        if tenant_name is not None:
            if not self.is_multi_tenant or not self.is_provider:
                raise BadTenantException('Tenant is only applicable to provider accounts in multi-tenant deployments')

            tenant_list = self.get('tenant').get('data')
            if tenant_list is None:
                raise RestAPIException('Could not retrieve vManage tenant list')

            for tenant in tenant_list:
                if tenant_name == tenant['name']:
                    session_id = self.post({}, 'tenant', tenant['tenantId'], 'vsessionid').get('VSessionId')
                    self.session.headers['VSessionId'] = session_id
                    self.is_tenant_scope = True
                    break
            else:
                raise BadTenantException(f'Invalid tenant: {tenant_name}')

        return True

    def logout(self):
        response = self.session.get(f'{self.base_url}/logout', params={'nocache': str(int(time()))})
        return response.status_code == requests.codes.ok

    @property
    def server_version(self):
        return self.server_facts.get('platformVersion')

    @property
    def is_multi_tenant(self):
        return self.server_facts.get('tenancyMode', '') == 'MultiTenant'

    @property
    def is_provider(self):
        return self.server_facts.get('userMode', '') == 'provider'

    def get(self, *path_entries, **params):
        response = self.session.get(self._url(*path_entries),
                                    params=params if params else None,
                                    timeout=self.timeout, verify=self.verify)
        raise_for_status(response)
        return response.json()

    def post(self, input_data, *path_entries):
        # With large input_data, vManage fails the post request if payload is encoded in compact form. Thus encoding
        # with indent=1.
        response = self.session.post(self._url(*path_entries), data=json.dumps(input_data, indent=1),
                                     timeout=self.timeout, verify=self.verify)
        raise_for_status(response)

        # POST may return an empty string, return None in this case
        return response.json() if response.text else None

    def put(self, input_data, *path_entries):
        # With large input_data, vManage fails the put request if payload is encoded in compact form. Thus encoding
        # with indent=1.
        response = self.session.put(self._url(*path_entries), data=json.dumps(input_data, indent=1),
                                    timeout=self.timeout, verify=self.verify)
        raise_for_status(response)

        # PUT may return an empty string, return None in this case
        return response.json() if response.text else None

    def delete(self, resource, key_value):
        response = self.session.delete(self._url(resource, key_value),
                                       timeout=self.timeout, verify=self.verify)
        return response.status_code == requests.codes.ok

    def _url(self, *path_entries):
        path = '/'.join(path.strip('/') for path in path_entries)

        return f'{self.base_url}/dataservice/{path}'


def raise_for_status(response):
    if response.status_code != requests.codes.ok:
        try:
            reply_data = response.json() if response.text else {}
        except json.decoder.JSONDecodeError:
            reply_data = {'error': {'message': 'Check user permissions'}} if response.status_code == 403 else {}

        raise RestAPIException(f'{response.reason} ({response.status_code}): '
                               f'{reply_data.get("error", {}).get("message", "Unspecified error message")} '
                               f'[{response.request.method} {response.url}]')


def is_version_newer(version_1, version_2):
    """
    Indicates whether one vManage version is newer than another. Compares only the first 2 digits from version
    because maintenance (i.e. 3rd digit) differences are not likely to create any incompatibility between REST API JSON
    payloads, thus not relevant in this context.

    Versions should be strings with fields separated by dots in format: <main>.<minor>.<maintenance>

    :param version_1: String containing first version
    :param version_2: String containing second version
    :return: True if version_2 is newer than version_1.
    """
    def parse(version_string):
        # Development versions may follow this format: '20.1.999-98'
        return ([int(v) for v in version_string.replace('-', '.').split('.')] + [0, ])[:2]

    return parse(version_2) > parse(version_1)


class RestAPIException(Exception):
    """ Exception for REST API errors """
    pass


class LoginFailedException(RestAPIException):
    """ Login failure """
    pass


class BadTenantException(RestAPIException):
    """ Provided tenant is invalid or not applicable """
    pass
