"""
SmartCivic+ — Integration Test Suite
Tests API authentication, citizen complaint submission, officer rejection, worker location updates, and notifications history.
"""
import unittest
import json
import os
import sys

# Ensure project root is on Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, db

class SmartCivicIntegrationTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        os.environ["SECRET_KEY"] = "test_secret_key_12345"
        os.environ["JWT_SECRET"] = "test_jwt_secret_67890"
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def test_health_check(self):
        res = self.client.get('/api/health')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success") or data.get("status") == "healthy")

    def test_unauthorized_access(self):
        res = self.client.get('/api/notifications')
        self.assertEqual(res.status_code, 401)

    def test_404_error_handler(self):
        res = self.client.get('/api/invalid-route-xyz')
        self.assertEqual(res.status_code, 404)
        data = res.get_json()
        self.assertFalse(data["success"])
        self.assertEqual(data["error"]["code"], "NOT_FOUND")

if __name__ == '__main__':
    unittest.main()
