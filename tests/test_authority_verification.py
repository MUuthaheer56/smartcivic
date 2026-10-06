import unittest
from app import create_app, db
from routes.auth import generate_tokens
from bson import ObjectId


class TestAuthorityResidentVerification(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def tearDown(self):
        db.users.delete_many({"email": {"$regex": "^test_pending_.*@smartcivic.com|^test_officer_.*@smartcivic.com"}})

    def test_pending_residents_are_listed_and_can_be_verified(self):
        resident_id = ObjectId()
        resident = {
            "_id": resident_id,
            "name": "Test Pending Resident",
            "email": "test_pending_resident@smartcivic.com",
            "password_hash": "hashed",
            "role": "resident",
            "verified": False,
            "verification_status": "pending",
            "status": "pending_verification",
            "ward": "Ward 12"
        }
        db.users.insert_one(resident)

        officer_id = ObjectId()
        officer = {
            "_id": officer_id,
            "name": "Test Officer",
            "email": "test_officer_pending@smartcivic.com",
            "password_hash": "hashed",
            "role": "officer",
            "ward": "Ward 12"
        }
        db.users.insert_one(officer)

        with self.app.app_context():
            token, _ = generate_tokens(str(officer_id), "officer", "Ward 12")

        self.client.set_cookie("access_token", token)
        pending_response = self.client.get("/api/auth/users/pending")
        self.assertEqual(pending_response.status_code, 200)
        self.assertTrue(pending_response.is_json)
        pending_data = pending_response.get_json()
        self.assertTrue(pending_data["success"])
        ids = [item["_id"] for item in pending_data["data"]]
        self.assertIn(str(resident_id), ids)

        verify_response = self.client.post(
            f"/api/auth/users/{resident_id}/verify",
            json={"action": "approve", "ward_id": "ward_12"},
        )
        self.assertEqual(verify_response.status_code, 200)
        verify_payload = verify_response.get_json()
        self.assertTrue(verify_payload["success"])

        updated = db.users.find_one({"_id": resident_id})
        self.assertEqual(updated["verification_status"], "approved")
        self.assertEqual(updated["status"], "active")
        self.assertTrue(updated["verified"])


if __name__ == "__main__":
    unittest.main()
