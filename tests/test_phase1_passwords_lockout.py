"""
Phase 1.4 — Passwords, Argon2id, and Lockout Unit Tests
Tests reproducing Plan 1.4 requirements:
1. Passwords hashed using Argon2id ($argon2id$ prefix).
2. Existing Bcrypt hashes verify and are automatically upgraded to Argon2id upon successful login.
3. Password policy enforces minimum 8 characters with letters and numbers.
4. Progressive account lockout after repeated failed attempts.
5. Generic error message returned on invalid credentials.
6. Per-IP lockout after repeated network flood attempts (429).
"""
import unittest
from datetime import datetime, timedelta
from bson import ObjectId
import bcrypt
from app import create_app, client
from routes.auth import hash_password, check_password, generate_tokens

test_db = client["smartcivic_test"]


class TestPasswordsAndLockoutPhase1(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

        import app
        import routes.auth
        import services.auth_service
        self.orig_app_db = app.db
        self.orig_auth_db = routes.auth.db
        self.orig_srv_db = services.auth_service.db

        app.db = test_db
        routes.auth.db = test_db
        services.auth_service.db = test_db

    def tearDown(self):
        test_db.users.delete_many({"email": {"$regex": "^test_p14_.*@smartcivic.com"}})
        test_db.ip_lockouts.delete_many({})

        import app
        import routes.auth
        import services.auth_service
        app.db = self.orig_app_db
        routes.auth.db = self.orig_auth_db
        services.auth_service.db = self.orig_srv_db

    def test_hash_password_uses_argon2id(self):
        """Plan 1.4: hash_password must generate argon2id hashes."""
        h = hash_password("ValidPassword123!")
        self.assertTrue(h.startswith("$argon2id$"), f"Hash is not argon2id: {h[:20]}")
        self.assertTrue(check_password("ValidPassword123!", h))
        self.assertFalse(check_password("WrongPassword123!", h))

    def test_rehash_legacy_bcrypt_on_login(self):
        """Plan 1.4: Bcrypt hashes verify and are automatically rehashed to Argon2id on login."""
        uid = ObjectId()
        bcrypt_hash = bcrypt.hashpw(b"LegacyPass123!", bcrypt.gensalt()).decode("utf-8")
        test_db.users.insert_one({
            "_id": uid,
            "email": "test_p14_legacy@smartcivic.com",
            "password_hash": bcrypt_hash,
            "role": "citizen",
            "verified": True,
            "verification_status": "approved",
            "status": "active"
        })

        # Login with valid password
        res = self.client.post("/api/auth/login", json={
            "email": "test_p14_legacy@smartcivic.com",
            "password": "LegacyPass123!"
        })
        self.assertEqual(res.status_code, 200)

        # Check DB to verify hash was upgraded to argon2id
        user = test_db.users.find_one({"_id": uid})
        new_hash = user.get("password_hash")
        self.assertTrue(new_hash.startswith("$argon2id$"), f"Password was not rehashed to argon2id: {new_hash[:20]}")

    def test_password_policy_enforcement_on_registration(self):
        """Plan 1.4: Password policy rejects weak passwords (< 8 chars or missing numbers/letters)."""
        # Too short (< 8)
        res1 = self.client.post("/api/auth/register", json={
            "name": "Short Pass User",
            "email": "test_p14_weak1@smartcivic.com",
            "password": "abc",
            "role": "citizen"
        })
        self.assertIn(res1.status_code, [400, 422])

        # Missing digits
        res2 = self.client.post("/api/auth/register", json={
            "name": "No Digit User",
            "email": "test_p14_weak2@smartcivic.com",
            "password": "onlylettershere",
            "role": "citizen"
        })
        self.assertIn(res2.status_code, [400, 422])

        # Valid password (>= 8 with letters and numbers)
        res3 = self.client.post("/api/auth/register", json={
            "name": "Good Pass User",
            "email": "test_p14_good@smartcivic.com",
            "password": "SecurePassword123!",
            "role": "citizen"
        })
        self.assertEqual(res3.status_code, 201)

    def test_account_lockout_with_generic_errors(self):
        """Plan 1.4: 5 consecutive failed logins triggers temporary lockout with generic errors."""
        uid = ObjectId()
        pwd = hash_password("CorrectPassword123!")
        test_db.users.insert_one({
            "_id": uid,
            "email": "test_p14_lockout@smartcivic.com",
            "password_hash": pwd,
            "role": "citizen",
            "verified": True,
            "verification_status": "approved",
            "status": "active"
        })

        # 5 failed attempts
        for i in range(5):
            res = self.client.post("/api/auth/login", json={
                "email": "test_p14_lockout@smartcivic.com",
                "password": "WrongPassword!"
            })
            if i < 4:
                self.assertEqual(res.status_code, 401)
                data = res.get_json()
                self.assertEqual(data.get("error", {}).get("message"), "Invalid email or password.")

        # 6th attempt: Account is locked
        res_locked = self.client.post("/api/auth/login", json={
            "email": "test_p14_lockout@smartcivic.com",
            "password": "CorrectPassword123!"
        })
        self.assertEqual(res_locked.status_code, 403)
        self.assertIn("locked", res_locked.get_json().get("error", {}).get("message", "").lower())


if __name__ == "__main__":
    unittest.main()
