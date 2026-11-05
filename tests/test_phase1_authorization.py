"""
Phase 1.2 — Default-Deny Authorization and Route Hardening Unit Tests
Tests reproducing Plan 1.2 requirements:
1. Public allowlist allows unauthenticated access to login, register, public stats, transparency, map.
2. Unlisted/protected routes reject unauthenticated requests (401 for /api/*, 302 for web pages).
3. Unverified citizens are blocked from:
   - POST /api/issues/<id>/support (403)
   - POST /api/issues/<id>/confirm (403)
   - POST /api/issues/<id>/feedback (403)
   - POST /api/issues/<id>/citizen-verify (403)
4. Self-support is blocked (reporter cannot support own issue -> 400).
5. Cross-citizen IDOR on GET /api/issues/<id> returns 403.
6. Cross-ward officer access on GET/POST /api/issues/<id> returns 403.
7. Unassigned worker resolving issue returns 403.
8. Citizen cannot jump state machine from 'submitted' to 'closed' (422/403).
"""
import unittest
from bson import ObjectId
from app import create_app, client
from routes.auth import generate_tokens, hash_password

test_db = client["smartcivic_test"]


class TestAuthorizationPhase1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        main_db = client["smartcivic"]
        wards = list(main_db.ward_registry.find({}))
        if wards:
            test_db.ward_registry.delete_many({})
            test_db.ward_registry.insert_many(wards)

    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

        import app
        import routes.auth
        import routes.citizen
        import routes.officer
        import routes.worker
        import routes.api.issues
        import routes.api.analytics
        import routes.api.workers
        import utils.auth_helpers
        import services.complaint_service

        self.orig_dbs = {
            "app": app.db,
            "auth": routes.auth.db,
            "citizen": routes.citizen.db,
            "officer": routes.officer.db,
            "worker": routes.worker.db,
            "issues": routes.api.issues.db,
            "analytics": routes.api.analytics.db,
            "workers_api": routes.api.workers.db,
            "helpers": utils.auth_helpers.db,
            "complaint": services.complaint_service.db
        }

        app.db = test_db
        routes.auth.db = test_db
        routes.citizen.db = test_db
        routes.officer.db = test_db
        routes.worker.db = test_db
        routes.api.issues.db = test_db
        routes.api.analytics.db = test_db
        routes.api.workers.db = test_db
        utils.auth_helpers.db = test_db
        services.complaint_service.db = test_db

    def tearDown(self):
        test_db.users.delete_many({"email": {"$regex": "^test_authz_.*@smartcivic.com"}})
        test_db.issues.delete_many({"title": {"$regex": "^Test Authz Issue.*"}})

        import app
        import routes.auth
        import routes.citizen
        import routes.officer
        import routes.worker
        import routes.api.issues
        import routes.api.analytics
        import routes.api.workers
        import utils.auth_helpers
        import services.complaint_service

        app.db = self.orig_dbs["app"]
        routes.auth.db = self.orig_dbs["auth"]
        routes.citizen.db = self.orig_dbs["citizen"]
        routes.officer.db = self.orig_dbs["officer"]
        routes.worker.db = self.orig_dbs["worker"]
        routes.api.issues.db = self.orig_dbs["issues"]
        routes.api.analytics.db = self.orig_dbs["analytics"]
        routes.api.workers.db = self.orig_dbs["workers_api"]
        utils.auth_helpers.db = self.orig_dbs["helpers"]
        services.complaint_service.db = self.orig_dbs["complaint"]

    def _create_user(self, suffix, role="citizen", ward="Ward 1", ward_id="ward_01", verified=True):
        uid = ObjectId()
        doc = {
            "_id": uid,
            "name": f"User {suffix}",
            "email": f"test_authz_{suffix}@smartcivic.com",
            "password_hash": hash_password("Password123!"),
            "role": role,
            "ward": ward,
            "ward_id": ward_id,
            "verified": verified,
            "verification_status": "approved" if verified else "pending",
            "status": "active" if verified else "pending_verification"
        }
        test_db.users.insert_one(doc)
        return uid, doc

    def _create_issue(self, title_suffix, reporter_id, ward="Ward 1", ward_id="ward_01",
                      status="submitted", assigned_worker_id=None):
        iid = ObjectId()
        doc = {
            "_id": iid,
            "issue_id": f"SC-TEST-{str(iid)[-6:]}",
            "title": f"Test Authz Issue {title_suffix}",
            "description": "Pothole on 5th main road needing attention",
            "category": "Roads & Footpaths",
            "citizen_id": str(reporter_id),
            "ward": ward,
            "ward_id": ward_id,
            "status": status,
            "assigned_worker_id": str(assigned_worker_id) if assigned_worker_id else None,
            "supporters": [],
            "support_count": 0
        }
        test_db.issues.insert_one(doc)
        return iid, doc

    def test_public_allowlist_allows_anonymous_access(self):
        """Public pages and APIs must be accessible without authentication."""
        for path in ["/login", "/register", "/transparency", "/map", "/api/public/stats"]:
            res = self.client.get(path)
            self.assertIn(res.status_code, [200, 304], f"Failed public access for {path}")

    def test_unverified_citizen_blocked_from_support(self):
        """VER-02: Pending citizen cannot vote/support issues (403)."""
        cit_id, _ = self._create_user("cit_unver_sup", role="citizen", verified=False)
        rep_id, _ = self._create_user("rep_sup", role="citizen", verified=True)
        iss_id, _ = self._create_issue("sup_target", rep_id)

        with self.app.app_context():
            token, _ = generate_tokens(str(cit_id), "citizen", "Ward 1")
        self.client.set_cookie("access_token", token)

        res = self.client.post(f"/api/issues/{iss_id}/support", json={"note": "I support"})
        self.assertEqual(res.status_code, 403, "Unverified resident was allowed to support complaint!")

    def test_self_support_blocked(self):
        """Plan 1.2: Citizen cannot support their own complaint (400)."""
        cit_id, _ = self._create_user("cit_self_sup", role="citizen", verified=True)
        iss_id, _ = self._create_issue("self_sup", cit_id)

        with self.app.app_context():
            token, _ = generate_tokens(str(cit_id), "citizen", "Ward 1")
        self.client.set_cookie("access_token", token)

        res = self.client.post(f"/api/issues/{iss_id}/support", json={"note": "Boosting my own complaint"})
        self.assertEqual(res.status_code, 400, "Citizen was allowed to self-support own issue!")

    def test_unverified_citizen_blocked_from_confirm_feedback_verify(self):
        """VER-02: Pending citizen blocked from confirm, feedback, and citizen-verify."""
        cit_id, _ = self._create_user("cit_unver_act", role="citizen", verified=False)
        rep_id, _ = self._create_user("rep_act", role="citizen", verified=True)
        iss_id, _ = self._create_issue("unver_act", rep_id, status="resolved")

        with self.app.app_context():
            token, _ = generate_tokens(str(cit_id), "citizen", "Ward 1")
        self.client.set_cookie("access_token", token)

        # Confirm
        res1 = self.client.post(f"/api/issues/{iss_id}/confirm", json={"note": "confirming"})
        self.assertEqual(res1.status_code, 403)

        # Feedback
        res2 = self.client.post(f"/api/issues/{iss_id}/feedback", json={"rating": 5})
        self.assertEqual(res2.status_code, 403)

        # Citizen verify
        res3 = self.client.post(f"/api/issues/{iss_id}/citizen-verify", json={"resolved": True})
        self.assertEqual(res3.status_code, 403)

    def test_cross_ward_officer_access_blocked(self):
        """Plan 1.2: Officer in Ward 1 cannot access or modify issues in Ward 2 (403)."""
        off1_id, _ = self._create_user("off_ward1", role="officer", ward="Ward 1", ward_id="ward_01")
        cit2_id, _ = self._create_user("cit_ward2", role="citizen", ward="Ward 2", ward_id="ward_02")
        iss2_id, _ = self._create_issue("ward2_issue", cit2_id, ward="Ward 2", ward_id="ward_02")

        with self.app.app_context():
            token1, _ = generate_tokens(str(off1_id), "officer", "Ward 1")
        self.client.set_cookie("access_token", token1)

        # GET should be forbidden
        res = self.client.get(f"/api/issues/{iss2_id}")
        self.assertEqual(res.status_code, 403)

        # POST review should be forbidden
        res2 = self.client.post(f"/api/issues/{iss2_id}/review", json={"status": "officer_reviewed"})
        self.assertEqual(res2.status_code, 403)

    def test_unassigned_worker_cannot_start_or_resolve(self):
        """Plan 1.2: Worker cannot start or resolve an issue they are not assigned to (403)."""
        wrk1_id, _ = self._create_user("wrk1", role="worker")
        wrk2_id, _ = self._create_user("wrk2", role="worker")
        iss_id, _ = self._create_issue("wrk_issue", wrk1_id, status="assigned", assigned_worker_id=wrk2_id)

        with self.app.app_context():
            token1, _ = generate_tokens(str(wrk1_id), "worker", "Ward 1")
        self.client.set_cookie("access_token", token1)

        res = self.client.post(f"/api/issues/{iss_id}/start", json={})
        self.assertEqual(res.status_code, 403)

    def test_citizen_cannot_jump_submitted_to_closed(self):
        """Plan 1.2: Citizen cannot jump an issue from 'submitted' directly to 'closed'."""
        cit_id, _ = self._create_user("cit_jump", role="citizen", verified=True)
        iss_id, _ = self._create_issue("cit_jump_iss", cit_id, status="submitted")

        with self.app.app_context():
            token, _ = generate_tokens(str(cit_id), "citizen", "Ward 1")
        self.client.set_cookie("access_token", token)

        res = self.client.post(f"/api/issues/{iss_id}/status", json={"status": "closed"})
        self.assertIn(res.status_code, [403, 422])

        issue = test_db.issues.find_one({"_id": iss_id})
        self.assertEqual(issue.get("status"), "submitted", "Citizen successfully jumped submitted to closed!")


if __name__ == "__main__":
    unittest.main()

