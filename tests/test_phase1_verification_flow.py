"""
Phase 1.1 — Verification Flow Unit Tests
Tests reproducing VER-01 through VER-10 and verifying:
1. verify-ward does NOT self-approve resident.
2. verify-ward returns 400 on unknown ward/area code.
3. Rejected user blocked at login with 403 or redirect to status.
4. manual_verify_user validates ObjectId (returns 400, not 500).
5. manual_verify_user returns 404 on nonexistent user.
6. Rejection requires reason of at least 10 chars (400/422).
7. Officers cannot approve/reject outside their assigned ward jurisdiction (403).
8. Officer cannot overwrite resident's ward during approval.
9. Approvals and rejections write audit_logs entries.
10. Approvals/rejections are idempotent.
11. GET /api/auth/verification-status returns rejection_reason.
"""
import unittest
from bson import ObjectId
from app import create_app, client, Config
from routes.auth import generate_tokens, hash_password

# Target smartcivic_test database
test_db = client["smartcivic_test"]


class TestVerificationFlowPhase1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Sync ward registry to test_db for realistic testing
        main_db = client["smartcivic"]
        wards = list(main_db.ward_registry.find({}))
        if wards:
            test_db.ward_registry.delete_many({})
            test_db.ward_registry.insert_many(wards)

    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

        # Patch app db to test_db for tests
        import app
        import routes.auth
        import routes.citizen
        import utils.auth_helpers
        self.orig_app_db = app.db
        self.orig_auth_db = routes.auth.db
        self.orig_citizen_db = routes.citizen.db
        self.orig_helpers_db = utils.auth_helpers.db

        app.db = test_db
        routes.auth.db = test_db
        routes.citizen.db = test_db
        utils.auth_helpers.db = test_db

    def tearDown(self):
        test_db.users.delete_many({"email": {"$regex": "^test_p1_.*@smartcivic.com"}})
        test_db.audit_logs.delete_many({"action": {"$in": ["resident_verification_approved", "resident_verification_rejected"]}})
        import app
        import routes.auth
        import routes.citizen
        import utils.auth_helpers
        app.db = self.orig_app_db
        routes.auth.db = self.orig_auth_db
        routes.citizen.db = self.orig_citizen_db
        utils.auth_helpers.db = self.orig_helpers_db

    def _create_user(self, email_suffix, role="citizen", ward="Ward 1", ward_id="ward_01",
                     verified=False, v_status="pending", status="pending_verification", password="Password123!"):
        uid = ObjectId()
        doc = {
            "_id": uid,
            "name": f"Test User {email_suffix}",
            "email": f"test_p1_{email_suffix}@smartcivic.com",
            "password_hash": hash_password(password),
            "role": role,
            "ward": ward,
            "ward_id": ward_id,
            "verified": verified,
            "verification_status": v_status,
            "status": status
        }
        test_db.users.insert_one(doc)
        return uid, doc

    def test_verify_ward_does_not_self_approve(self):
        """VER-01: Valid ward code should update pending ward request but NEVER set verified=True."""
        uid, _ = self._create_user("verify_no_auto", role="citizen")
        with self.app.app_context():
            token, _ = generate_tokens(str(uid), "citizen", "Ward 1")

        self.client.set_cookie("access_token", token)
        res = self.client.post("/api/auth/verify-ward", json={"area_code": "KDM-001"})
        self.assertEqual(res.status_code, 200)

        user = test_db.users.find_one({"_id": uid})
        # MUST NOT be self-approved
        self.assertFalse(user.get("verified"), "Security failure: resident auto-approved themselves!")
        self.assertEqual(user.get("verification_status"), "pending")
        self.assertEqual(user.get("ward_id"), "ward_01")

    def test_verify_ward_unknown_code_returns_400(self):
        """VER-01: Unknown area code must return 400 Bad Request."""
        uid, _ = self._create_user("verify_bad_code", role="citizen")
        with self.app.app_context():
            token, _ = generate_tokens(str(uid), "citizen", "Ward 1")

        self.client.set_cookie("access_token", token)
        res = self.client.post("/api/auth/verify-ward", json={"area_code": "NONEXISTENT_CODE_999"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("error", res.get_json())

    def test_rejected_user_blocked_at_login(self):
        """VER-03 / Plan 1.1: Rejected residents must be blocked at login with 403."""
        self._create_user("rejected_login", role="citizen", verified=False,
                          v_status="rejected", status="rejected", password="SecretPassword123!")

        res = self.client.post("/api/auth/login", json={
            "email": "test_p1_rejected_login@smartcivic.com",
            "password": "SecretPassword123!"
        })
        self.assertEqual(res.status_code, 403)
        data = res.get_json()
        self.assertFalse(data.get("success", False))

    def test_manual_verify_invalid_objectid_returns_400(self):
        """VER-07: Invalid user_id format in approve/reject must return 400, not 500 crash."""
        officer_id, _ = self._create_user("off_inv_id", role="officer", ward="Ward 1", ward_id="ward_01")
        with self.app.app_context():
            token, _ = generate_tokens(str(officer_id), "officer", "Ward 1")

        self.client.set_cookie("access_token", token)
        res = self.client.post("/api/auth/users/not-a-valid-id/approve", json={})
        self.assertEqual(res.status_code, 400)
        self.assertIn("error", res.get_json())

    def test_manual_verify_nonexistent_user_returns_404(self):
        """VER-08: Nonexistent user_id in approve/reject must return 404, not 200."""
        officer_id, _ = self._create_user("off_nonexist", role="officer", ward="Ward 1", ward_id="ward_01")
        with self.app.app_context():
            token, _ = generate_tokens(str(officer_id), "officer", "Ward 1")

        nonexistent_id = str(ObjectId())
        self.client.set_cookie("access_token", token)
        res = self.client.post(f"/api/auth/users/{nonexistent_id}/approve", json={})
        self.assertEqual(res.status_code, 404)

    def test_manual_reject_requires_rejection_reason_min_10_chars(self):
        """VER-09: Rejection without a reason or with reason < 10 chars must return 400/422."""
        officer_id, _ = self._create_user("off_rej_val", role="officer", ward="Ward 1", ward_id="ward_01")
        resident_id, _ = self._create_user("res_to_reject", role="citizen", ward="Ward 1", ward_id="ward_01")

        with self.app.app_context():
            token, _ = generate_tokens(str(officer_id), "officer", "Ward 1")
        self.client.set_cookie("access_token", token)

        # Missing reason
        res1 = self.client.post(f"/api/auth/users/{resident_id}/reject", json={})
        self.assertIn(res1.status_code, [400, 422])

        # Too short reason (< 10 chars)
        res2 = self.client.post(f"/api/auth/users/{resident_id}/reject", json={"reason": "bad doc"})
        self.assertIn(res2.status_code, [400, 422])

        # Valid reason >= 10 chars
        res3 = self.client.post(f"/api/auth/users/{resident_id}/reject", json={"reason": "Address proof does not match municipal ward"})
        self.assertEqual(res3.status_code, 200)

        user = test_db.users.find_one({"_id": resident_id})
        self.assertEqual(user.get("verification_status"), "rejected")
        self.assertEqual(user.get("rejection_reason"), "Address proof does not match municipal ward")

    def test_manual_verify_enforces_ward_jurisdiction(self):
        """VER-05: Officer in Ward 1 cannot approve or reject resident in Ward 2 (403)."""
        off1_id, _ = self._create_user("off_ward1", role="officer", ward="Ward 1", ward_id="ward_01")
        res_ward2_id, _ = self._create_user("res_ward2", role="citizen", ward="Ward 2", ward_id="ward_02")

        with self.app.app_context():
            token1, _ = generate_tokens(str(off1_id), "officer", "Ward 1")

        self.client.set_cookie("access_token", token1)
        res = self.client.post(f"/api/auth/users/{res_ward2_id}/approve", json={})
        self.assertEqual(res.status_code, 403, "Security failure: cross-ward approval was not rejected with 403!")

    def test_officer_cannot_overwrite_resident_ward(self):
        """Plan 1.1: Officers must not overwrite a resident's ward with arbitrary input."""
        off1_id, _ = self._create_user("off_ward1_ovr", role="officer", ward="Ward 1", ward_id="ward_01")
        res_ward1_id, _ = self._create_user("res_ward1_ovr", role="citizen", ward="Ward 1", ward_id="ward_01")

        with self.app.app_context():
            token1, _ = generate_tokens(str(off1_id), "officer", "Ward 1")

        self.client.set_cookie("access_token", token1)
        # Malicious officer payload attempts to move resident to ward_99
        res = self.client.post(f"/api/auth/users/{res_ward1_id}/approve", json={"ward_id": "ward_99"})
        self.assertEqual(res.status_code, 200)

        user = test_db.users.find_one({"_id": res_ward1_id})
        self.assertEqual(user.get("ward_id"), "ward_01", "Officer overwrote resident ward!")

    def test_manual_verify_writes_audit_log(self):
        """VER-06: Approvals and rejections must record audit log entries."""
        off1_id, _ = self._create_user("off_audit", role="officer", ward="Ward 1", ward_id="ward_01")
        res_id, _ = self._create_user("res_audit", role="citizen", ward="Ward 1", ward_id="ward_01")

        with self.app.app_context():
            token1, _ = generate_tokens(str(off1_id), "officer", "Ward 1")

        self.client.set_cookie("access_token", token1)
        res = self.client.post(f"/api/auth/users/{res_id}/approve", json={})
        self.assertEqual(res.status_code, 200)

        log = test_db.audit_logs.find_one({
            "target_user_id": str(res_id),
            "action": "resident_verification_approved"
        })
        self.assertIsNotNone(log, "Audit log missing for resident approval!")
        self.assertEqual(log.get("actor_id"), str(off1_id))

    def test_manual_verify_is_idempotent(self):
        """VER-10: Approving an already approved user returns 200 without error."""
        off1_id, _ = self._create_user("off_idem", role="officer", ward="Ward 1", ward_id="ward_01")
        res_id, _ = self._create_user("res_idem", role="citizen", ward="Ward 1", ward_id="ward_01",
                                     verified=True, v_status="approved", status="active")

        with self.app.app_context():
            token1, _ = generate_tokens(str(off1_id), "officer", "Ward 1")

        self.client.set_cookie("access_token", token1)
        res = self.client.post(f"/api/auth/users/{res_id}/approve", json={})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))

    def test_verification_status_returns_rejection_reason(self):
        """VER-04: /verification-status returns rejection_reason."""
        res_id, _ = self._create_user("res_status_rej", role="citizen", verified=False,
                                      v_status="rejected", status="rejected")
        test_db.users.update_one({"_id": res_id}, {"$set": {"rejection_reason": "Invalid electricity bill"}})

        with self.app.app_context():
            token, _ = generate_tokens(str(res_id), "citizen", "Ward 1")

        self.client.set_cookie("access_token", token)
        res = self.client.get("/api/auth/verification-status")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("rejection_reason"), "Invalid electricity bill")

    def test_require_citizen_page_redirects_unverified_residents(self):
        """VER-03: Pending/unverified citizens cannot access citizen dashboard or report page."""
        res_id, _ = self._create_user("res_page_unver", role="citizen", verified=False,
                                      v_status="pending", status="pending_verification")
        with self.app.app_context():
            token, _ = generate_tokens(str(res_id), "citizen", "Ward 1")

        self.client.set_cookie("access_token", token)
        res = self.client.get("/citizen/dashboard")
        self.assertEqual(res.status_code, 302)
        self.assertIn("/citizen/verify-ward", res.headers.get("Location", ""))

        res2 = self.client.get("/report")
        self.assertEqual(res2.status_code, 302)
        self.assertIn("/citizen/verify-ward", res2.headers.get("Location", ""))


if __name__ == "__main__":
    unittest.main()
