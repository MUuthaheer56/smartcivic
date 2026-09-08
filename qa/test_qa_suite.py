"""
SmartCivic+ — Complete QA Automated Test Suite
"""
import unittest
import json
import os
import secrets
import io
import sys
from datetime import datetime, timedelta
from bson import ObjectId

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, db
from routes.auth import hash_password, generate_tokens
from models.user import derive_citizen_tier
from services import ai_service, priority_service, sla_service, route_service

class SmartCivicFullQATestSuite(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        os.environ["SECRET_KEY"] = "test_qa_secret_key_1234567890"
        os.environ["JWT_SECRET"] = "test_qa_jwt_secret_0987654321"
        cls.qa_password = secrets.token_urlsafe(16)
        cls.qa_invite_code = secrets.token_urlsafe(20)
        os.environ["ADMIN_INVITE_CODE"] = cls.qa_invite_code
        
        cls.app = create_app()
        cls.app.config["ADMIN_INVITE_CODE"] = cls.qa_invite_code
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def setUp(self):
        # Create test users in DB for each role
        self.pwd = self.qa_password
        self.pwd_hash = hash_password(self.pwd)

        # Citizen 1 User
        self.citizen_id = ObjectId()
        db.users.delete_many({"email": "test_citizen_qa@smartcivic.com"})
        db.users.insert_one({
            "_id": self.citizen_id,
            "name": "QA Citizen 1",
            "email": "test_citizen_qa@smartcivic.com",
            "password_hash": self.pwd_hash,
            "role": "citizen",
            "ward": "Ward 1",
            "reputation_score": 55,
            "created_at": datetime.utcnow()
        })

        # Citizen 2 User (for community confirmations)
        self.citizen2_id = ObjectId()
        db.users.delete_many({"email": "test_citizen2_qa@smartcivic.com"})
        db.users.insert_one({
            "_id": self.citizen2_id,
            "name": "QA Citizen 2",
            "email": "test_citizen2_qa@smartcivic.com",
            "password_hash": self.pwd_hash,
            "role": "citizen",
            "ward": "Ward 1",
            "reputation_score": 55,
            "created_at": datetime.utcnow()
        })

        # Worker User
        self.worker_id = ObjectId()
        db.users.delete_many({"email": "test_worker_qa@smartcivic.com"})
        db.users.insert_one({
            "_id": self.worker_id,
            "name": "QA Worker",
            "email": "test_worker_qa@smartcivic.com",
            "password_hash": self.pwd_hash,
            "role": "worker",
            "ward": "Ward 1",
            "skills": ["road_repair", "roads", "road"],
            "current_location": {"type": "Point", "coordinates": [77.5946, 12.9716]},
            "is_available": True,
            "active_assignments": 0,
            "created_at": datetime.utcnow()
        })

        # Officer User
        self.officer_id = ObjectId()
        db.users.delete_many({"email": "test_officer_qa@smartcivic.com"})
        db.users.insert_one({
            "_id": self.officer_id,
            "name": "QA Officer",
            "email": "test_officer_qa@smartcivic.com",
            "password_hash": self.pwd_hash,
            "role": "officer",
            "ward": "all",
            "created_at": datetime.utcnow()
        })

        # Generate auth tokens
        with self.app.app_context():
            self.citizen_access, self.citizen_refresh = generate_tokens(str(self.citizen_id), "citizen", "Ward 1")
            self.citizen2_access, self.citizen2_refresh = generate_tokens(str(self.citizen2_id), "citizen", "Ward 1")
            self.worker_access, self.worker_refresh = generate_tokens(str(self.worker_id), "worker", "Ward 1")
            self.officer_access, self.officer_refresh = generate_tokens(str(self.officer_id), "officer", "all")

    def tearDown(self):
        db.users.delete_many({"email": {"$regex": "test_.*_qa@smartcivic.com"}})

    # ==================== 1. SECURITY & CONFIG ====================
    def test_security_headers_present(self):
        res = self.client.get('/api/health')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get('X-Content-Type-Options'), 'nosniff')
        self.assertEqual(res.headers.get('X-Frame-Options'), 'DENY')
        self.assertIn('Content-Security-Policy', res.headers)
        csp = res.headers.get('Content-Security-Policy')
        self.assertIn('tile.openstreetmap.org', csp)
        self.assertIn('router.project-osrm.org', csp)

    # ==================== 2. AUTHENTICATION & ACCESS CONTROL ====================
    def test_auth_register_citizen_success(self):
        payload = {
            "name": "New Citizen",
            "email": "new_citizen_qa@smartcivic.com",
            "password": self.qa_password,
            "role": "citizen",
            "ward": "Ward 2"
        }
        res = self.client.post('/auth/register', json=payload)
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertTrue(data["success"])
        db.users.delete_many({"email": "new_citizen_qa@smartcivic.com"})

    def test_auth_register_worker_requires_invite_code(self):
        # Missing invite code
        payload = {
            "name": "Unauthorized Worker",
            "email": "unauth_worker_qa@smartcivic.com",
            "password": self.qa_password,
            "role": "worker",
            "ward": "Ward 1"
        }
        res = self.client.post('/auth/register', json=payload)
        self.assertEqual(res.status_code, 403)

        # Valid invite code
        payload["invite_code"] = self.qa_invite_code
        res = self.client.post('/auth/register', json=payload)
        self.assertEqual(res.status_code, 201)
        db.users.delete_many({"email": "unauth_worker_qa@smartcivic.com"})

    def test_auth_login_success(self):
        res = self.client.post('/auth/login', json={
            "email": "test_citizen_qa@smartcivic.com",
            "password": self.qa_password
        })
        self.assertEqual(res.status_code, 200)
        self.assertIn('access_token', res.headers.get('Set-Cookie', ''))

    def test_auth_login_invalid_password(self):
        res = self.client.post('/auth/login', json={
            "email": "test_citizen_qa@smartcivic.com",
            "password": "wrongpassword123"
        })
        self.assertEqual(res.status_code, 401)

    def test_role_based_access_restriction(self):
        # Citizen attempting Officer-only route -> 403
        self.client.set_cookie('access_token', self.citizen_access)
        res = self.client.get('/api/analytics/overview')
        self.assertEqual(res.status_code, 403)

        # Officer accessing Officer route -> 200
        self.client.set_cookie('access_token', self.officer_access)
        res = self.client.get('/api/analytics/overview')
        self.assertEqual(res.status_code, 200)

    # ==================== 3. CITIZEN WORKFLOW ====================
    def test_citizen_create_issue_and_verify(self):
        self.client.set_cookie('access_token', self.citizen_access)
        
        # Submit complaint
        data = {
            "title": "Severe Pothole on Main St",
            "description": "Large deep pothole endangering vehicles near school",
            "category": "road",
            "type": "pothole",
            "lat": "12.9716",
            "lng": "77.5946",
            "address": "123 Main Street, Ward 1",
            "ward": "Ward 1"
        }
        res = self.client.post('/api/issues', data=data, content_type='multipart/form-data')
        self.assertEqual(res.status_code, 201)
        res_data = res.get_json()
        self.assertTrue(res_data["success"])
        issue_id = res_data["data"]["_id"]

        # Fetch complaint details
        res_detail = self.client.get(f'/api/issues/{issue_id}')
        self.assertEqual(res_detail.status_code, 200)
        self.assertEqual(res_detail.get_json()["data"]["title"], "Severe Pothole on Main St")

        # Declare emergency
        res_emerg = self.client.post(f'/api/issues/{issue_id}/declare-emergency', json={"emergency_category": "COLLAPSED_ROAD"})
        self.assertEqual(res_emerg.status_code, 200)

        # Crowd confirm issue using second citizen account (other than author)
        self.client.set_cookie('access_token', self.citizen2_access)
        res_confirm = self.client.post(f'/api/issues/{issue_id}/confirm', json={"note": "Confirmed by neighbor"})
        self.assertEqual(res_confirm.status_code, 200)

        # Cleanup created issue
        db.issues.delete_one({"_id": ObjectId(issue_id)})

    # ==================== 4. WORKER WORKFLOW ====================
    def test_worker_job_lifecycle(self):
        # Create an assigned issue for worker
        issue_id = ObjectId()
        db.issues.insert_one({
            "_id": issue_id,
            "title": "Water Leakage QA",
            "description": "Broken pipe leaking on street",
            "category": "water",
            "type": "water_leak",
            "severity": "high",
            "status": "assigned",
            "worker_id": self.worker_id,
            "citizen_id": self.citizen_id,
            "ward": "Ward 1",
            "location": {"type": "Point", "coordinates": [77.5946, 12.9716]},
            "created_at": datetime.utcnow()
        })

        # Worker lists assigned jobs
        self.client.set_cookie('access_token', self.worker_access)
        res_jobs = self.client.get('/api/worker/jobs')
        self.assertEqual(res_jobs.status_code, 200)
        jobs = res_jobs.get_json()["data"]
        self.assertTrue(any(j["_id"] == str(issue_id) for j in jobs))

        # Worker starts job
        res_start = self.client.post(f'/api/issues/{issue_id}/start')
        self.assertEqual(res_start.status_code, 200)
        updated_issue = db.issues.find_one({"_id": issue_id})
        self.assertEqual(updated_issue["status"], "work_started")

        # Worker updates GPS location
        res_loc = self.client.put('/api/workers/me/location', json={"lat": 12.9720, "lng": 77.5950})
        self.assertEqual(res_loc.status_code, 200)

        # Worker resolves job with proof photo
        data = {
            "notes": "Repaired broken pipe",
            "image": (io.BytesIO(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb\x00C\x00"), "proof.jpg")
        }
        res_resolve = self.client.post(f'/api/issues/{issue_id}/resolve', data=data, content_type='multipart/form-data')
        self.assertEqual(res_resolve.status_code, 200)
        resolved_issue = db.issues.find_one({"_id": issue_id})
        self.assertEqual(resolved_issue["status"], "work_completed")

        db.issues.delete_one({"_id": issue_id})

    # ==================== 5. OFFICER & ADMIN WORKFLOW ====================
    def test_officer_management_and_analytics(self):
        # Create an issue for recommendation test
        test_issue_id = ObjectId()
        db.issues.insert_one({
            "_id": test_issue_id,
            "title": "Road Repair Test",
            "category": "road",
            "type": "pothole",
            "status": "submitted",
            "ward": "Ward 1",
            "location": {"type": "Point", "coordinates": [77.5946, 12.9716]},
            "created_at": datetime.utcnow()
        })

        self.client.set_cookie('access_token', self.officer_access)

        # Overview analytics
        res_overview = self.client.get('/api/analytics/overview')
        self.assertEqual(res_overview.status_code, 200)

        # Ward analytics
        res_ward = self.client.get('/api/analytics/by-ward')
        self.assertEqual(res_ward.status_code, 200)

        # Department analytics
        res_dept = self.client.get('/api/analytics/by-department')
        self.assertEqual(res_dept.status_code, 200)

        # Worker recommendations
        res_rec = self.client.get(f'/api/workers/recommend?issue_id={test_issue_id}')
        self.assertEqual(res_rec.status_code, 200)

        # AI Copilot Q&A
        res_ask = self.client.post('/api/analytics/ask', json={"question": "How many road complaints in Ward 1?"})
        self.assertEqual(res_ask.status_code, 200)
        self.assertIn("answer", res_ask.get_json())

        # PDF Report download
        res_pdf = self.client.get('/api/analytics/weekly-report/pdf')
        self.assertEqual(res_pdf.status_code, 200)
        self.assertEqual(res_pdf.mimetype, 'application/pdf')

        db.issues.delete_one({"_id": test_issue_id})

    # ==================== 6. MAP & SPATIAL APIS ====================
    def test_map_and_spatial_endpoints(self):
        self.client.set_cookie('access_token', self.officer_access)

        self.assertEqual(self.client.get('/api/map/issues').status_code, 200)
        self.assertEqual(self.client.get('/api/map/clusters').status_code, 200)
        self.assertEqual(self.client.get('/api/map/heatmap').status_code, 200)
        self.assertEqual(self.client.get('/api/map/workers').status_code, 200)
        self.assertEqual(self.client.get('/api/public/map').status_code, 200)
        self.assertEqual(self.client.get('/api/map/infrastructure').status_code, 200)

    # ==================== 7. NOTIFICATIONS & INFRASTRUCTURE ====================
    def test_notifications_api(self):
        self.client.set_cookie('access_token', self.citizen_access)
        
        # Insert test notification
        notif_id = ObjectId()
        db.notifications.insert_one({
            "_id": notif_id,
            "user_id": self.citizen_id,
            "title": "Test Notification",
            "message": "Complaint updated",
            "is_read": False,
            "created_at": datetime.utcnow()
        })

        res_list = self.client.get('/api/notifications')
        self.assertEqual(res_list.status_code, 200)

        res_read = self.client.post(f'/api/notifications/{notif_id}/read')
        self.assertEqual(res_read.status_code, 200)

        db.notifications.delete_one({"_id": notif_id})

    # ==================== 8. FRONTEND PAGE LOADS ====================
    def test_frontend_page_renders(self):
        self.assertEqual(self.client.get('/login').status_code, 200)
        self.assertEqual(self.client.get('/register').status_code, 200)
        self.assertEqual(self.client.get('/transparency').status_code, 200)

        # Authenticated page renders
        self.client.set_cookie('access_token', self.citizen_access)
        self.assertEqual(self.client.get('/citizen/dashboard').status_code, 200)
        self.assertEqual(self.client.get('/report').status_code, 200)

        self.client.set_cookie('access_token', self.officer_access)
        self.assertEqual(self.client.get('/officer/dashboard').status_code, 200)

        self.client.set_cookie('access_token', self.worker_access)
        self.assertEqual(self.client.get('/worker/dashboard').status_code, 200)

if __name__ == '__main__':
    unittest.main()
