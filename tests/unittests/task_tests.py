import unittest
from cisco_sdwan.base.rest_api import Rest


VMANAGE_INFO = ("https:/198.18.1.10:443", "admin", "admin")


class TestTasks(unittest.TestCase):
    api: Rest = None

    @classmethod
    def setUpClass(cls) -> None:
        cls.api = Rest(*VMANAGE_INFO, timeout=120)

    def test_task_show_rt(self) -> None:
        ...

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.api is not None:
            cls.api.logout()
            cls.api.session.close()


if __name__ == '__main__':
    unittest.main()
