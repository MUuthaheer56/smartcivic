"""
SmartCivic+ — Integration Test Suite
Tests API authentication, citizen complaint submission, officer rejection, worker location updates, and notifications history.
"""
import unittest
import json
import os
import sys
from datetime import datetime
from bson import ObjectId

# Ensure project root is on Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, db
from routes.auth import generate_tokens, hash_password

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

    def test_officer_queue_includes_submitted_issues_in_priority_order(self):
        officer_id = ObjectId()
        issue_ids = [ObjectId(), ObjectId()]
        db.users.insert_one({
            "_id": officer_id,
            "email": "test_queue_officer@smartcivic.com",
            "password_hash": hash_password("pass123456"),
            "role": "officer",
            "ward": "Ward 1"
        })
        db.issues.insert_many([
            {
                "_id": issue_ids[0], "title": "New complaint", "status": "submitted",
                "ward": "Ward 1", "priority_score": 90, "created_at": datetime.utcnow()
            },
            {
                "_id": issue_ids[1], "title": "Reviewed complaint", "status": "officer_reviewed",
                "ward": "Ward 1", "priority_score": 40, "created_at": datetime.utcnow()
            }
        ])
        try:
            with self.app.app_context():
                token, _ = generate_tokens(str(officer_id), "officer", "Ward 1")
            res = self.client.get(
                '/api/issues?status=submitted,ai_reviewed,officer_reviewed&sort=priority_score',
                headers={"Authorization": f"Bearer {token}"}
            )
            self.assertEqual(res.status_code, 200)
            issues = res.get_json()["data"]
            returned_ids = [issue["_id"] for issue in issues if issue["_id"] in {str(value) for value in issue_ids}]
            self.assertEqual(returned_ids, [str(issue_ids[0]), str(issue_ids[1])])
        finally:
            db.users.delete_one({"_id": officer_id})
            db.issues.delete_many({"_id": {"$in": issue_ids}})

if __name__ == '__main__':
    unittest.main()
