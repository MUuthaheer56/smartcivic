"""
test_fixes_and_cefap.py — Verification script for Fixes 1, 2, 3 and CEFAP integration.
"""
import unittest
from datetime import datetime, timedelta
from bson import ObjectId

from app import create_app, db
from services.cefap_pipeline import cefap_stage, record_resolution_feedback

class TestSmartCivicFixesAndCEFAP(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.app.config["WTF_CSRF_ENABLED"] = False
        self.client = self.app.test_client()

        # Seed ward in ward_registry
        db.ward_registry.update_one(
            {"area_code": "WARD101"},
            {"$set": {
                "area_code": "WARD101",
                "ward_id": "ward_101",
                "ward_name": "Koramangala Ward 101",
                "active": True,
                "center_lat": 12.9352,
                "center_lng": 77.6245
            }},
            upsert=True
        )

    def test_fix1_registration_and_verification_flow(self):
        # 1. Register citizen
        email = f"citizen_test_{ObjectId()}@example.com"
        reg_payload = {
            "name": "Test Resident",
            "email": email,
            "password": "Password123!",
            "role": "resident"
        }
        res_reg = self.client.post('/api/auth/register', json=reg_payload)
        self.assertIn(res_reg.status_code, [200, 201])
        user_in_db = db.users.find_one({"email": email})
        self.assertIsNotNone(user_in_db)
        self.assertFalse(user_in_db.get("verified", True))
        self.assertEqual(user_in_db.get("status"), "pending_verification")

        # 2. Login
        login_res = self.client.post('/api/auth/login', json={
            "email": email,
            "password": "Password123!"
        })
        self.assertEqual(login_res.status_code, 200)
        login_data = login_res.get_json()
        token = login_data.get("access_token") or login_data["data"]["access_token"]
        user_info = login_data.get("user") or login_data["data"]["user"]
        self.assertFalse(user_info["verified"])
        self.assertEqual(user_info["role"], "resident")

        headers = {"Authorization": f"Bearer {token}"}

        # 3. Block complaint submission when unverified
        complaint_payload = {
            "title": "Unverified complaint attempt",
            "description": "Attempting to lodge a complaint without ward verification.",
            "category": "road",
            "type": "pothole",
            "ward": "Ward 101"
        }
        res_blocked = self.client.post('/api/issues', json=complaint_payload, headers=headers)
        self.assertEqual(res_blocked.status_code, 403)
        blocked_json = res_blocked.get_json()
        self.assertIn("Account not verified", blocked_json.get("error", ""))

        # 4. Verify Ward via area code
        res_verify = self.client.post('/api/auth/verify-ward', json={"area_code": "WARD101"}, headers=headers)
        self.assertEqual(res_verify.status_code, 200)
        verify_data = res_verify.get_json()
        self.assertEqual(verify_data.get("ward_id"), "ward_101")

        user_after = db.users.find_one({"email": email})
        self.assertTrue(user_after.get("verified"))
        self.assertEqual(user_after.get("status"), "active")

        # 5. Check /me endpoint
        me_res = self.client.get('/api/auth/me', headers=headers)
        self.assertEqual(me_res.status_code, 200)
        me_data = me_res.get_json()
        self.assertTrue(me_data.get("verified"))
        self.assertEqual(me_data.get("status"), "active")

        # 6. Complaint submission now succeeds
        res_success = self.client.post('/api/issues', json=complaint_payload, headers=headers)
        self.assertEqual(res_success.status_code, 201)

    def test_fix3_location_context(self):
        # Register and verify user to get token
        email = f"loc_user_{ObjectId()}@example.com"
        self.client.post('/api/auth/register', json={
            "name": "Location User",
            "email": email,
            "password": "Password123!",
            "role": "resident"
        })
        login_res = self.client.post('/api/auth/login', json={"email": email, "password": "Password123!"})
        token = login_res.get_json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        loc_res = self.client.get('/api/location/context?lat=12.9352&lng=77.6245', headers=headers)
        self.assertEqual(loc_res.status_code, 200)
        loc_data = loc_res.get_json()
        self.assertIn("ward_id", loc_data)
        self.assertIn("location_type", loc_data)

    def test_cefap_pipeline_calculation(self):
        params = {
            "issue_id": str(ObjectId()),
            "ward_id": "ward_101",
            "service": "roads",
            "text_severity": "critical",
            "text_confidence": 0.88,
            "image_severity": "high",
            "image_confidence": 0.90,
            "location_type": "hospital",
            "vote_count": 12,
            "historical_complaints": [{"created_at": datetime.utcnow() - timedelta(days=5)}],
            "created_at": datetime.utcnow(),
            "sla_deadline": None
        }
        res = cefap_stage(db, params)
        self.assertIn("cips", res)
        self.assertIn("priority", res)
        self.assertIn(res["priority"], ["P0", "P1", "P2", "P3"])
        self.assertTrue(0.0 <= res["cips"] <= 1.0)
        self.assertIn("signals", res)
        self.assertIn("weights", res)

if __name__ == "__main__":
    unittest.main()
