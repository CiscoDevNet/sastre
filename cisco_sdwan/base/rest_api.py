"""
 Sastre - Automation Tools for Cisco SD-WAN Powered by Viptela

 cisco_sdwan.base.rest_api
 This module implements the lower level REST API
"""
import requests
import urllib3


class Rest:
    def __init__(self, base_url, username, password, timeout=20, verify=False):
        self.base_url = base_url
        self.timeout = timeout
        self.verify = verify
        self.session = None
        self.server_facts = None

        if not verify:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        if not self.login(username, password):
            raise LoginFailedException('Login to {base_url} failed, check credentials'.format(base_url=self.base_url))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.session is not None:
            # In 19.3, logging out actually de-authorize all sessions a user may have from the same IP address. For
            # instance browser windows open from the same laptop. So for now, will not explicitly log out
            # self.logout()
            self.session.close()

        return False

    def login(self, username, password):
        data = {
            'j_username': username,
            'j_password': password
        }

        session = requests.Session()
        response = session.post('{base_url}/j_security_check'.format(base_url=self.base_url),
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

        return True

    def logout(self):
        response = self.session.get('{base_url}/logout?nocache'.format(base_url=self.base_url))
        return response.status_code == requests.codes.ok

    @property
    def server_version(self):
        return self.server_facts.get('platformVersion')

    def get(self, *path_entries):
        response = self.session.get(self._url(*path_entries),
                                    timeout=self.timeout, verify=self.verify)
        raise_for_status(response)
        return response.json()

    def post(self, input_data, *path_entries):
        response = self.session.post(self._url(*path_entries), json=input_data,
                                     timeout=self.timeout, verify=self.verify)
        raise_for_status(response)

        # POST may return an empty string, return None in this case
        return response.json() if response.text else None

    def put(self, input_data, *path_entries):
        response = self.session.put(self._url(*path_entries), json=input_data,
                                    timeout=self.timeout, verify=self.verify)
        raise_for_status(response)

        # PUT may return an empty string, return None in this case
        return response.json() if response.text else None

    def delete(self, resource, key_value):
        response = self.session.delete(self._url(resource, key_value),
                                       timeout=self.timeout, verify=self.verify)
        return response.status_code == requests.codes.ok

    def _url(self, *path_entries):
        return '{base_url}/dataservice/{path}'.format(base_url=self.base_url,
                                                      path='/'.join(path.strip('/') for path in path_entries))


def raise_for_status(response_obj):
    if response_obj.status_code != requests.codes.ok:
        reply_data = response_obj.json() if response_obj.text else {}
        raise RestAPIException('{r.reason} ({r.status_code}): {error} [{r.request.method} {r.url}]'.format(
            r=response_obj, error=reply_data.get('error', {}).get('message', 'Unspecified error message')))


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
        return ([int(v) for v in version_string.split('.')] + [0, ])[:2]

    return parse(version_2) > parse(version_1)


class RestAPIException(Exception):
    """ Exception for REST API errors """
    pass


class LoginFailedException(RestAPIException):
    """ Login failure """
    pass
