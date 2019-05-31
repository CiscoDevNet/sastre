"""
vManage REST API

"""

import requests
import urllib3


class Rest:
    def __init__(self, base_url, username, password, timeout=20, verify=False):
        self.base_url = base_url
        self.timeout = timeout
        self.verify = verify
        self.session = None

        if not verify:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        if not self.login(username, password):
            raise LoginFailedException('Login to {base_url} failed, check credentials'.format(base_url=self.base_url))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.session is not None:
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
        return True

    def get(self, *path_entries):
        response = self.session.get(self._url(*path_entries),
                                    timeout=self.timeout, verify=self.verify)
        response.raise_for_status()
        return response.json()

    def post(self, input_data, *path_entries):
        response = self.session.post(self._url(*path_entries), json=input_data,
                                     timeout=self.timeout, verify=self.verify)
        response.raise_for_status()
        return response.json()

    def put(self, input_data, resource, key_value):
        response = self.session.put(self._url(resource, key_value), json=input_data,
                                    timeout=self.timeout, verify=self.verify)
        return response.status_code == requests.codes.ok

    def delete(self, resource, key_value):
        response = self.session.delete(self._url(resource, key_value),
                                       timeout=self.timeout, verify=self.verify)
        return response.status_code == requests.codes.ok

    def _url(self, *path_entries):
        return '{base_url}/dataservice/{path}'.format(base_url=self.base_url,
                                                      path='/'.join(map(lambda x: x.strip('/'), path_entries)))


class RestAPIException(Exception):
    """ Exception for REST API errors """
    pass


class LoginFailedException(RestAPIException):
    """ Login failure """
    pass
