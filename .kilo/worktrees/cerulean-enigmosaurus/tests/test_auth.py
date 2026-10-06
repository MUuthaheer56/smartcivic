"""
SmartCivic — Auth Unit Tests
Tests registration, login, role enforcement, and token decoding.
"""
import unittest
from app import create_app, db
from routes.auth import generate_tokens, hash_password
from services.auth_service import register_user, login_user, check_role
from bson import ObjectId

class TestAuth(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        
    def tearDown(self):
        db.users.delete_many({"email": {"$regex": "^test_.*@smartcivic.com"}})

    def test_resident_registration(self):
        res = register_user("test_resident@smartcivic.com", "pass123456", "resident", "Test Resident")
        self.assertIn("user_id", res)
        self.assertEqual(res["role"], "resident")

    def test_officer_and_worker_login(self):
        pwd = hash_password("secure123")
        db.users.insert_one({"_id": ObjectId(), "email": "test_officer@smartcivic.com", "password_hash": pwd, "role": "officer", "ward": "all"})
        db.users.insert_one({"_id": ObjectId(), "email": "test_worker@smartcivic.com", "password_hash": pwd, "role": "worker", "ward": "Ward 1"})
        
        with self.app.app_context():
            off_res = login_user("test_officer@smartcivic.com", "secure123")
            self.assertEqual(off_res["role"], "officer")
            self.assertIn("access_token", off_res)
            
            wrk_res = login_user("test_worker@smartcivic.com", "secure123")
            self.assertEqual(wrk_res["role"], "worker")

    def test_invalid_token_401(self):
        res = self.client.get("/auth/me", headers={"Authorization": "Bearer invalid.jwt.token"})
        self.assertEqual(res.status_code, 401)

    def test_resident_access_officer_route_forbidden(self):
        uid = ObjectId()
        db.users.insert_one({"_id": uid, "email": "test_res_auth@smartcivic.com", "password_hash": hash_password("pwd"), "role": "resident"})
        with self.app.app_context():
            tok, _ = generate_tokens(str(uid), "resident", "Ward 1")
        
        self.client.set_cookie("access_token", tok)
        res = self.client.get("/api/workers")
        self.assertEqual(res.status_code, 403)

if __name__ == "__main__":
    unittest.main()
