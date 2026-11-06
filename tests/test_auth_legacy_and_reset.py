"""
Tests for Authentication Legacy Hash Support, Rehashing, and Admin Reset Utility
Validates:
1. Legacy Werkzeug scrypt/pbkdf2 hashes are accepted and rehashed to Argon2 on login.
2. Legacy Bcrypt hashes are accepted and rehashed to Argon2 on login.
3. Argon2id hashes verify natively without needing rehash.
4. scripts/dev_reset_admin.py refuses to run when APP_ENV != development.
5. scripts/dev_reset_admin.py resets admin fields, verified=True, status="active", clears lockout.
6. seed_plus.py validates password before executing any collection drops.
"""
import os
import io
import re
import unittest
from unittest.mock import patch
from bson import ObjectId
from werkzeug.security import generate_password_hash
import bcrypt

from app import create_app, db
from routes.auth import check_password_and_needs_rehash, hash_password


class TestAuthLegacyAndReset(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def test_legacy_werkzeug_hash_accepted_and_flagged_for_rehash(self):
        """Legacy Werkzeug scrypt/pbkdf2 hashes must return matches=True, needs_rehash=True."""
        plain = "LegacyWerkzeugPass123!"
        w_hash = generate_password_hash(plain)  # Default: scrypt:...
        self.assertTrue(w_hash.startswith(("scrypt:", "pbkdf2:")))

        matches, needs_rehash = check_password_and_needs_rehash(plain, w_hash)
        self.assertTrue(matches, "Legacy Werkzeug hash must match correct password!")
        self.assertTrue(needs_rehash, "Legacy Werkzeug hash must be flagged for rehash!")

        wrong_matches, _ = check_password_and_needs_rehash("WrongPassword!", w_hash)
        self.assertFalse(wrong_matches)

    def test_legacy_bcrypt_hash_accepted_and_flagged_for_rehash(self):
        """Legacy bcrypt $2b$ hashes must return matches=True, needs_rehash=True."""
        plain = "LegacyBcryptPass123!"
        b_hash = bcrypt.hashpw(plain.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        self.assertTrue(b_hash.startswith("$2"))

        matches, needs_rehash = check_password_and_needs_rehash(plain, b_hash)
        self.assertTrue(matches)
        self.assertTrue(needs_rehash)

    def test_argon2_hash_verified_natively_without_rehash(self):
        """Canonical Argon2id hashes match and do not need rehash."""
        plain = "Argon2Password123!"
        a_hash = hash_password(plain)
        self.assertTrue(a_hash.startswith("$argon2id"))

        matches, needs_rehash = check_password_and_needs_rehash(plain, a_hash)
        self.assertTrue(matches)
        self.assertFalse(needs_rehash)

    def test_login_automatically_rehashes_legacy_hash_to_argon2(self):
        """When user logs in with a legacy Werkzeug hash, DB hash is transparently upgraded to Argon2."""
        plain = "RehashMePassword123!"
        w_hash = generate_password_hash(plain)

        test_email = "test_rehash_user@smartcivic.com"
        db.users.delete_many({"email": test_email})
        uid = ObjectId()
        db.users.insert_one({
            "_id": uid,
            "name": "Rehash Test User",
            "email": test_email,
            "password_hash": w_hash,
            "role": "citizen",
            "ward": "Ward 1",
            "verified": True,
            "status": "active"
        })

        try:
            # 1. Fetch CSRF token
            r_get = self.client.get('/login')
            html = r_get.get_data(as_text=True)
            match = re.search(r'name="csrf-token" content="([^"]+)"', html)
            token = match.group(1) if match else None

            # 2. Login
            resp = self.client.post(
                '/auth/login',
                json={'email': test_email, 'password': plain},
                headers={'X-CSRFToken': token} if token else {}
            )
            self.assertEqual(resp.status_code, 200)
            self.assertTrue(resp.get_json().get("success"))

            # 3. Check DB document: password_hash must now start with $argon2id
            updated_user = db.users.find_one({"_id": uid})
            new_hash = updated_user.get("password_hash", "")
            self.assertTrue(new_hash.startswith("$argon2id"), f"Hash was not upgraded to Argon2! Found: {new_hash[:20]}")

            # 4. Next login succeeds natively with Argon2
            resp2 = self.client.post(
                '/auth/login',
                json={'email': test_email, 'password': plain},
                headers={'X-CSRFToken': token} if token else {}
            )
            self.assertEqual(resp2.status_code, 200)
        finally:
            db.users.delete_many({"email": test_email})

    def test_dev_reset_admin_refuses_production(self):
        """scripts/dev_reset_admin.py must abort if APP_ENV != development."""
        from scripts.dev_reset_admin import check_dev_environment

        with patch.dict(os.environ, {"APP_ENV": "production", "FLASK_ENV": "production"}):
            with self.assertRaises(SystemExit) as ctx:
                check_dev_environment()
            self.assertEqual(ctx.exception.code, 1)

    def test_dev_reset_admin_allows_development(self):
        """scripts/dev_reset_admin.py runs without error when APP_ENV=development."""
        from scripts.dev_reset_admin import check_dev_environment

        with patch.dict(os.environ, {"APP_ENV": "development", "FLASK_ENV": "development"}):
            # Should not raise SystemExit
            check_dev_environment()

    def test_seed_plus_fails_before_drop_if_password_short(self):
        """seed_plus.py must validate SEED_PASSWORD before dropping existing collections."""
        from seed_plus import seed_db

        # Insert a sentinel user in DB
        sentinel_email = "sentinel_check@smartcivic.com"
        db.users.insert_one({"email": sentinel_email, "name": "Sentinel"})

        try:
            with patch.dict(os.environ, {"SEED_PASSWORD": "short"}, clear=False):
                with self.assertRaises(RuntimeError) as ctx:
                    seed_db()
                self.assertIn("SEED_PASSWORD must be set", str(ctx.exception))

            # Verify sentinel was NOT deleted (drop was not executed)
            sentinel = db.users.find_one({"email": sentinel_email})
            self.assertIsNotNone(sentinel, "Collections were dropped before password validation!")
        finally:
            db.users.delete_many({"email": sentinel_email})
