"""
Phase 1.3 — Authorization Test Matrix
Runs routes across 9 caller personas:
1. anonymous
2. pending
3. rejected
4. citizen_a (Ward 1, owner of Issue A)
5. citizen_b (Ward 2, owner of Issue B)
6. worker (assigned to Issue A)
7. officer_w1 (Ward 1)
8. officer_w2 (Ward 2)
9. admin (global)

Enforces exact expected HTTP response codes for every cell in the authorization matrix.
"""
import unittest
from bson import ObjectId
from app import create_app, client
from routes.auth import generate_tokens, hash_password

test_db = client["smartcivic_test"]


class TestAuthzMatrixPhase1(unittest.TestCase):
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

        for k in self.orig_dbs:
            pass

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

        self._setup_fixtures()

    def tearDown(self):
        test_db.users.delete_many({"email": {"$regex": "^matrix_.*@smartcivic.com"}})
        test_db.issues.delete_many({"title": {"$regex": "^Matrix Issue.*"}})

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

    def _create_user(self, name, email_prefix, role, ward="Ward 1", ward_id="ward_01",
                     verified=True, v_status="approved", status="active"):
        uid = ObjectId()
        doc = {
            "_id": uid,
            "name": name,
            "email": f"matrix_{email_prefix}@smartcivic.com",
            "password_hash": hash_password("MatrixPassword123!"),
            "role": role,
            "ward": ward,
            "ward_id": ward_id,
            "verified": verified,
            "verification_status": v_status,
            "status": status
        }
        test_db.users.insert_one(doc)
        return uid, doc

    def _setup_fixtures(self):
        # 1. Anonymous (None)
        # 2. Pending resident
        self.pending_id, _ = self._create_user("Pending", "pending", "citizen", verified=False, v_status="pending", status="pending_verification")
        # 3. Rejected resident
        self.rejected_id, _ = self._create_user("Rejected", "rejected", "citizen", verified=False, v_status="rejected", status="rejected")
        # 4. Citizen A (Ward 1)
        self.cit_a_id, _ = self._create_user("Citizen A", "cita", "citizen", ward="Ward 1", ward_id="ward_01")
        # 5. Citizen B (Ward 2)
        self.cit_b_id, _ = self._create_user("Citizen B", "citb", "citizen", ward="Ward 2", ward_id="ward_02")
        # 6. Worker
        self.worker_id, _ = self._create_user("Worker", "worker", "worker", ward="Ward 1", ward_id="ward_01")
        # 7. Officer Ward 1
        self.off_w1_id, _ = self._create_user("Officer W1", "offw1", "officer", ward="Ward 1", ward_id="ward_01")
        # 8. Officer Ward 2
        self.off_w2_id, _ = self._create_user("Officer W2", "offw2", "officer", ward="Ward 2", ward_id="ward_02")
        # 9. Admin
        self.admin_id, _ = self._create_user("Admin", "admin", "admin", ward="all")

        # Create Issue A in Ward 1 owned by Citizen A and assigned to Worker
        self.issue_a_id = ObjectId()
        test_db.issues.insert_one({
            "_id": self.issue_a_id,
            "issue_id": f"SC-MAT-{str(self.issue_a_id)[-6:]}",
            "title": "Matrix Issue A",
            "description": "Issue in Ward 1",
            "category": "Roads & Footpaths",
            "citizen_id": str(self.cit_a_id),
            "ward": "Ward 1",
            "ward_id": "ward_01",
            "status": "assigned",
            "assigned_worker_id": str(self.worker_id),
            "worker_id": str(self.worker_id),
            "supporters": [],
            "support_count": 0
        })

        # Precompute JWT tokens
        with self.app.app_context():
            self.tokens = {
                "anonymous": None,
                "pending": generate_tokens(str(self.pending_id), "citizen", "Ward 1")[0],
                "rejected": generate_tokens(str(self.rejected_id), "citizen", "Ward 1")[0],
                "citizen_a": generate_tokens(str(self.cit_a_id), "citizen", "Ward 1")[0],
                "citizen_b": generate_tokens(str(self.cit_b_id), "citizen", "Ward 2")[0],
                "worker": generate_tokens(str(self.worker_id), "worker", "Ward 1")[0],
                "officer_w1": generate_tokens(str(self.off_w1_id), "officer", "Ward 1")[0],
                "officer_w2": generate_tokens(str(self.off_w2_id), "officer", "Ward 2")[0],
                "admin": generate_tokens(str(self.admin_id), "admin", "all")[0]
            }

    def _execute_request(self, persona, method, path, json_data=None):
        token = self.tokens[persona]
        # Clear cookies first
        self.client.delete_cookie("access_token")
        headers = {}
        if token:
            self.client.set_cookie("access_token", token)
            headers["Authorization"] = f"Bearer {token}"

        if method == "GET":
            return self.client.get(path, headers=headers)
        elif method == "POST":
            return self.client.post(path, json=json_data or {}, headers=headers)
        raise ValueError(f"Unsupported method {method}")

    def test_run_authz_matrix(self):
        """
        Executes the master authorization matrix across all 9 personas.
        Fails if any persona receives an unexpected status code.
        """
        personas = [
            "anonymous", "pending", "rejected", "citizen_a", "citizen_b",
            "worker", "officer_w1", "officer_w2", "admin"
        ]

        # Matrix definition: (Method, Path_Template, JSON_Payload, {persona: expected_status_or_list})
        matrix = [
            # Public Pages / APIs
            ("GET", "/login", None,
             {p: [200, 304] for p in personas}),
            ("GET", "/transparency", None,
             {p: [200, 304] for p in personas}),
            ("GET", "/api/public/stats", None,
             {p: [200, 304] for p in personas}),

            # Citizen Pages
            ("GET", "/citizen/dashboard", None, {
                "anonymous": 302,
                "pending": 302,
                "rejected": 302,
                "citizen_a": 200,
                "citizen_b": 200,
                "worker": 302,
                "officer_w1": 302,
                "officer_w2": 302,
                "admin": 302
            }),
            ("GET", "/report", None, {
                "anonymous": 302,
                "pending": 302,
                "rejected": 302,
                "citizen_a": 200,
                "citizen_b": 200,
                "worker": 302,
                "officer_w1": 302,
                "officer_w2": 302,
                "admin": 302
            }),

            # Officer Dashboard
            ("GET", "/officer/dashboard", None, {
                "anonymous": 302,
                "pending": 302,
                "rejected": 302,
                "citizen_a": 302,
                "citizen_b": 302,
                "worker": 302,
                "officer_w1": 200,
                "officer_w2": 200,
                "admin": 200
            }),

            # Worker Dashboard
            ("GET", "/worker/dashboard", None, {
                "anonymous": 302,
                "pending": 302,
                "rejected": 302,
                "citizen_a": 302,
                "citizen_b": 302,
                "worker": 200,
                "officer_w1": 302,
                "officer_w2": 302,
                "admin": 302
            }),

            # Verification Queue API
            ("GET", "/api/auth/users/pending", None, {
                "anonymous": 401,
                "pending": 403,
                "rejected": 403,
                "citizen_a": 403,
                "citizen_b": 403,
                "worker": 403,
                "officer_w1": 200,
                "officer_w2": 200,
                "admin": 200
            }),

            # Ward 1 Resident Approval (Target is pending_id in Ward 1)
            ("POST", f"/api/auth/users/{self.pending_id}/approve", {}, {
                "anonymous": 401,
                "pending": 403,
                "rejected": 403,
                "citizen_a": 403,
                "citizen_b": 403,
                "worker": 403,
                "officer_w1": 200,
                "officer_w2": 403,  # Cross-ward forbidden!
                "admin": 200
            }),

            # Issue A Access (Ward 1, Owned by Citizen A, Assigned to Worker)
            ("GET", f"/api/issues/{self.issue_a_id}", None, {
                "anonymous": 401,
                "pending": 403,
                "rejected": 403,
                "citizen_a": 200,  # Owner
                "citizen_b": 403,  # IDOR
                "worker": 200,     # Assigned Worker
                "officer_w1": 200, # Same ward
                "officer_w2": 403, # Cross-ward
                "admin": 200      # Admin
            }),

            # Issue A Review (Officer Only, Ward 1)
            ("POST", f"/api/issues/{self.issue_a_id}/review", {"category": "Roads & Footpaths"}, {
                "anonymous": 401,
                "pending": 403,
                "rejected": 403,
                "citizen_a": 403,
                "citizen_b": 403,
                "worker": 403,
                "officer_w1": 200,
                "officer_w2": 403, # Cross-ward
                "admin": 200
            }),

            # Workers List API
            ("GET", "/api/workers", None, {
                "anonymous": 401,
                "pending": 403,
                "rejected": 403,
                "citizen_a": 403,
                "citizen_b": 403,
                "worker": 403,
                "officer_w1": 200,
                "officer_w2": 200,
                "admin": 200
            }),

            # Worker Jobs API
            ("GET", "/api/workers/tasks", None, {
                "anonymous": 401,
                "pending": 403,
                "rejected": 403,
                "citizen_a": 403,
                "citizen_b": 403,
                "worker": 200,
                "officer_w1": 403,
                "officer_w2": 403,
                "admin": 403
            })
        ]

        matrix_failures = []
        for method, path, body, expectations in matrix:
            for persona in personas:
                expected = expectations[persona]
                if not isinstance(expected, list):
                    expected = [expected]

                res = self._execute_request(persona, method, path, body)
                if res.status_code not in expected:
                    matrix_failures.append(
                        f"FAILED: {persona} {method} {path} -> received {res.status_code}, expected {expected}"
                    )

        if matrix_failures:
            self.fail("\n".join(matrix_failures))


if __name__ == "__main__":
    unittest.main()
