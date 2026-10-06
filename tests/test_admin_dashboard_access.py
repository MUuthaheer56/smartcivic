import unittest
from app import create_app, db
from routes.auth import generate_tokens
from bson import ObjectId


class TestAdminDashboardAccess(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def tearDown(self):
        db.users.delete_many({"email": {"$regex": "^test_admin_dashboard_.*@smartcivic.com"}})

    def test_admin_can_access_dashboard_and_pending_verification_queue(self):
        admin_id = ObjectId()
        db.users.insert_one({
            "_id": admin_id,
            "name": "Admin Authority",
            "email": "test_admin_dashboard_authority@smartcivic.com",
            "password_hash": "hashed",
            "role": "admin",
            "ward": "Ward 12"
        })

        with self.app.app_context():
            token, _ = generate_tokens(str(admin_id), "admin", "Ward 12")

        self.client.set_cookie("access_token", token)
        dashboard_response = self.client.get("/admin/dashboard")
        self.assertEqual(dashboard_response.status_code, 200)

        pending_response = self.client.get("/api/auth/users/pending")
        self.assertEqual(pending_response.status_code, 200)
        payload = pending_response.get_json()
        self.assertTrue(payload["success"])


if __name__ == "__main__":
    unittest.main()
