import unittest
from src.auth import AuthService

class TestAuthService(unittest.TestCase):
    def test_authenticate_user(self):
        service = AuthService()
        self.assertTrue(service.authenticate_user("admin", "secret-admin"))
        self.assertFalse(service.authenticate_user("admin", "wrong-secret"))
        self.assertFalse(service.authenticate_user("", ""))
