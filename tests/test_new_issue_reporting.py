"""
tests/test_new_issue_reporting.py - Comprehensive Regression Suite for 2.3 NEW ISSUE REPORT
Covers:
1. Valid submission lifecycle and visibility across:
   - Officer New Issues queue
   - Citizen My Reports
   - Public / Live Map
2. Category, Priority, Authority, and SLA assignments
3. Edge test: No photo (allowed, text pipeline fallback)
4. Edge test: Huge photo (>8MB / >5MB rejected with 400/413)
5. Edge test: Bad file type (malicious/exe/non-image rejected with 400)
6. Edge test: Missing or invalid location (rejected with 400)
7. Edge test: Duplicate nearby report handling
8. Edge test: Pending / unverified citizen rejection (403)
9. Edge test: Multilingual (Kannada) description intake & translation
10. Edge test: Emergency report escalation (P0 priority)
11. CTVE clarification submission
"""

import io
import os
import unittest
from bson import ObjectId
from PIL import Image

from app import create_app, db
from routes.auth import generate_tokens


class TestNewIssueReportingRegression(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.app.config["WTF_CSRF_ENABLED"] = False  # Bearer token API tests
        self.client = self.app.test_client()

        self.ward = "Ward 150 - Bellandur"
        self.citizen_id = ObjectId()
        self.pending_citizen_id = ObjectId()
        self.officer_id = ObjectId()

        # Seed test accounts
        db.users.insert_many([
            {
                "_id": self.citizen_id,
                "email": f"verified_{self.citizen_id}@test.com",
                "role": "citizen",
                "ward": self.ward,
                "ward_id": "ward_150",
                "verified": True,
                "verification_status": "verified",
                "status": "active"
            },
            {
                "_id": self.pending_citizen_id,
                "email": f"pending_{self.pending_citizen_id}@test.com",
                "role": "citizen",
                "ward": self.ward,
                "ward_id": "ward_150",
                "verified": False,
                "verification_status": "pending",
                "status": "pending_verification"
            },
            {
                "_id": self.officer_id,
                "email": f"officer_{self.officer_id}@test.com",
                "role": "officer",
                "ward": "ALL",
                "verified": True,
                "status": "active"
            }
        ])

        with self.app.app_context():
            self.citizen_token, _ = generate_tokens(str(self.citizen_id), "citizen", self.ward)
            self.pending_token, _ = generate_tokens(str(self.pending_citizen_id), "citizen", self.ward)
            self.officer_token, _ = generate_tokens(str(self.officer_id), "officer", "ALL")

        self.created_issue_ids = []

    def tearDown(self):
        if self.created_issue_ids:
            db.issues.delete_many({"_id": {"$in": self.created_issue_ids}})
            db.audit_logs.delete_many({"entity_id": {"$in": [str(i) for i in self.created_issue_ids]}})
            db.clusters.delete_many({"ward": self.ward})
        db.users.delete_many({"_id": {"$in": [self.citizen_id, self.pending_citizen_id, self.officer_id]}})

    def _create_dummy_image(self, size=(100, 100), fmt="JPEG"):
        buf = io.BytesIO()
        img = Image.new("RGB", size, color=(200, 50, 50))
        img.save(buf, format=fmt)
        buf.seek(0)
        return buf

    def test_valid_report_lifecycle_and_visibility(self):
        """1. Submission appears in officer New Issues, citizen My Reports, and live map; has correct attrs."""
        img_buf = self._create_dummy_image()
        data = {
            "title": "Severe Pothole on Outer Ring Road",
            "description": "Deep dangerous pothole causing vehicular damage near Bellandur eco-space.",
            "category": "road",
            "type": "pothole",
            "latitude": "12.9250",
            "longitude": "77.6800",
            "address": "Outer Ring Road, Bellandur, Bengaluru",
            "ward": self.ward,
            "image": (img_buf, "pothole.jpg", "image/jpeg")
        }

        resp = self.client.post(
            "/api/issues",
            data=data,
            content_type="multipart/form-data",
            headers={"Authorization": f"Bearer {self.citizen_token}"}
        )
        self.assertEqual(resp.status_code, 201, resp.get_json())
        body = resp.get_json()
        self.assertTrue(body["success"])
        issue_id_str = body["issue_id"]

        # Find in DB
        issue = db.issues.find_one({"$or": [{"_id": ObjectId(issue_id_str) if ObjectId.is_valid(issue_id_str) else None}, {"issue_id": issue_id_str}]})
        self.assertIsNotNone(issue)
        self.created_issue_ids.append(issue["_id"])

        # Check Category, Priority, Authority, SLA
        self.assertEqual(issue["category"], "road")
        self.assertIn(issue["priority"], ["P0", "P1", "P2", "P3"])
        self.assertTrue("sla" in issue or "sla_deadline" in issue)
        self.assertTrue("authority_primary" in issue or "department" in issue)
        self.assertEqual(issue["status"], "submitted")

        # 1. Officer New Issues Queue
        off_resp = self.client.get(
            "/api/issues?status=submitted",
            headers={"Authorization": f"Bearer {self.officer_token}"}
        )
        self.assertEqual(off_resp.status_code, 200)
        off_issues = off_resp.get_json().get("data", [])
        found_in_officer = any(i.get("issue_id") == issue.get("issue_id") or str(i.get("_id")) == str(issue["_id"]) for i in off_issues)
        self.assertTrue(found_in_officer, "Issue must appear in Officer New Issues queue")

        # 2. Citizen My Reports
        cit_resp = self.client.get(
            "/api/citizen/issues",
            headers={"Authorization": f"Bearer {self.citizen_token}"}
        )
        self.assertEqual(cit_resp.status_code, 200)
        cit_issues = cit_resp.get_json().get("data", [])
        found_in_citizen = any(i.get("issue_id") == issue.get("issue_id") or str(i.get("_id")) == str(issue["_id"]) for i in cit_issues)
        self.assertTrue(found_in_citizen, "Issue must appear in Citizen My Reports")

        # 3. Live Map
        map_resp = self.client.get(
            "/api/map/issues",
            headers={"Authorization": f"Bearer {self.officer_token}"}
        )
        self.assertEqual(map_resp.status_code, 200)
        map_issues = map_resp.get_json().get("data", [])
        found_in_map = any(
            i.get("issue_id") == issue.get("issue_id") or
            str(i.get("_id")) == str(issue["_id"]) or
            str(i.get("id")) == str(issue["_id"])
            for i in map_issues
        )
        self.assertTrue(found_in_map, "Issue must appear in Live Map issues list")

    def test_report_without_photo_allowed(self):
        """2. Issue report without photo succeeds with text-only AI analysis."""
        data = {
            "title": "Streetlight Not Working",
            "description": "Streetlight pole number 42 has been dark for three consecutive nights.",
            "category": "electrical",
            "type": "streetlight",
            "latitude": "12.9260",
            "longitude": "77.6810",
            "address": "Bellandur 5th Cross, Bengaluru",
            "ward": self.ward
        }
        resp = self.client.post(
            "/api/issues",
            data=data,
            headers={"Authorization": f"Bearer {self.citizen_token}"}
        )
        self.assertEqual(resp.status_code, 201, resp.get_json())
        body = resp.get_json()
        issue = db.issues.find_one({"issue_id": body["issue_id"]})
        self.assertIsNotNone(issue)
        self.created_issue_ids.append(issue["_id"])
        self.assertEqual(issue["status"], "submitted")

    def test_report_huge_photo_rejected(self):
        """3. Huge photo (>5MB/8MB) rejected with 400 or 413."""
        huge_bytes = io.BytesIO(b"X" * (8 * 1024 * 1024 + 1024))
        data = {
            "title": "Huge Photo Issue",
            "description": "Attempting upload of oversized payload to test limit.",
            "latitude": "12.9250",
            "longitude": "77.6800",
            "image": (huge_bytes, "huge.jpg", "image/jpeg")
        }
        resp = self.client.post(
            "/api/issues",
            data=data,
            content_type="multipart/form-data",
            headers={"Authorization": f"Bearer {self.citizen_token}"}
        )
        self.assertIn(resp.status_code, [400, 413])

    def test_report_bad_file_rejected(self):
        """4. Bad file format (exe/malicious script disguised) rejected with 400 SECURITY_ERROR."""
        fake_file = io.BytesIO(b"MZ\x90\x00\x03\x00\x00\x00fake_executable_binary_content")
        data = {
            "title": "Executable Upload Attack",
            "description": "Attempting to upload executable disguised as jpg.",
            "latitude": "12.9250",
            "longitude": "77.6800",
            "image": (fake_file, "exploit.exe", "application/x-msdownload")
        }
        resp = self.client.post(
            "/api/issues",
            data=data,
            content_type="multipart/form-data",
            headers={"Authorization": f"Bearer {self.citizen_token}"}
        )
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertEqual(body.get("error", {}).get("code"), "SECURITY_ERROR")

    def test_report_invalid_location_rejected(self):
        """5. Invalid latitude/longitude rejected with 400 VALIDATION_ERROR."""
        data = {
            "title": "Invalid Coordinates",
            "description": "Submitting impossible latitude exceeding bounds.",
            "latitude": "999.999",
            "longitude": "77.6800"
        }
        resp = self.client.post(
            "/api/issues",
            data=data,
            headers={"Authorization": f"Bearer {self.citizen_token}"}
        )
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertEqual(body.get("error", {}).get("code"), "VALIDATION_ERROR")

    def test_report_unverified_pending_citizen_rejected(self):
        """6. Pending unverified citizen cannot file issues (403 Forbidden)."""
        data = {
            "title": "Pending Citizen Report",
            "description": "Unverified citizen trying to bypass ward verification.",
            "latitude": "12.9250",
            "longitude": "77.6800"
        }
        resp = self.client.post(
            "/api/issues",
            data=data,
            headers={"Authorization": f"Bearer {self.pending_token}"}
        )
        self.assertEqual(resp.status_code, 403)

    def test_report_kannada_multilingual_handling(self):
        """7. Kannada text in description handled and processed without encoding crash."""
        data = {
            "title": "ರಸ್ತೆ ಗುಂಡಿ",
            "description": "ಬೆಳ್ಳಂದೂರು ಮುಖ್ಯ ರಸ್ತೆಯಲ್ಲಿ ದೊಡ್ಡ ಗುಂಡಿ ಬಿದ್ದಿದೆ ಮತ್ತು ಸಂಚಾರಕ್ಕೆ ತೊಂದರೆಯಾಗಿದೆ.",
            "latitude": "12.9250",
            "longitude": "77.6800",
            "category": "road",
            "ward": self.ward
        }
        resp = self.client.post(
            "/api/issues",
            data=data,
            headers={"Authorization": f"Bearer {self.citizen_token}"}
        )
        self.assertEqual(resp.status_code, 201, resp.get_json())
        body = resp.get_json()
        issue = db.issues.find_one({"issue_id": body["issue_id"]})
        self.assertIsNotNone(issue)
        self.created_issue_ids.append(issue["_id"])
        self.assertIn("ಗುಂಡಿ", issue.get("original_description", "") or issue.get("description", ""))

    def test_report_emergency_text_escalates_priority(self):
        """8. Emergency text triggers immediate emergency flag and P0 priority."""
        data = {
            "title": "Live Wire Sparking on Road",
            "description": "High voltage live electrical cable snapped, actively sparking and danger of electrocution on public street.",
            "category": "electrical",
            "latitude": "12.9250",
            "longitude": "77.6800",
            "ward": self.ward
        }
        resp = self.client.post(
            "/api/issues",
            data=data,
            headers={"Authorization": f"Bearer {self.citizen_token}"}
        )
        self.assertEqual(resp.status_code, 201, resp.get_json())
        body = resp.get_json()
        issue = db.issues.find_one({"issue_id": body["issue_id"]})
        self.assertIsNotNone(issue)
        self.created_issue_ids.append(issue["_id"])
        self.assertEqual(issue.get("priority"), "P0")
        self.assertTrue(bool(issue.get("emergency")) or issue.get("emergency_state") in ("IMMEDIATE_112", "SAFETY_REVIEW", True))

    def test_duplicate_nearby_reporting(self):
        """9. Duplicate report nearby is detected or clustered."""
        # 1. First report
        data1 = {
            "title": "Deep Pothole at Junction",
            "description": "Hazardous road pothole right at junction.",
            "category": "road",
            "latitude": "12.9250",
            "longitude": "77.6800",
            "ward": self.ward
        }
        resp1 = self.client.post(
            "/api/issues",
            data=data1,
            headers={"Authorization": f"Bearer {self.citizen_token}"}
        )
        self.assertEqual(resp1.status_code, 201)
        issue1 = db.issues.find_one({"issue_id": resp1.get_json()["issue_id"]})
        self.created_issue_ids.append(issue1["_id"])

        # 2. Duplicate nearby report
        data2 = {
            "title": "Deep Pothole at Junction",
            "description": "Hazardous road pothole right at junction.",
            "category": "road",
            "latitude": "12.9250",
            "longitude": "77.6800",
            "ward": self.ward
        }
        resp2 = self.client.post(
            "/api/issues",
            data=data2,
            headers={"Authorization": f"Bearer {self.citizen_token}"}
        )
        self.assertEqual(resp2.status_code, 201)
        body2 = resp2.get_json()
        issue2 = db.issues.find_one({"issue_id": body2["issue_id"]})
        self.created_issue_ids.append(issue2["_id"])

        # Check duplicate info or same cluster
        is_dup = issue2.get("duplicate", {}).get("is_duplicate", False)
        same_cluster = (issue1.get("cluster_id") and issue1.get("cluster_id") == issue2.get("cluster_id"))
        self.assertTrue(is_dup or same_cluster or issue2.get("duplicate_of") is not None, "Nearby identical issue must be flagged as duplicate or clustered")


    def test_ctve_modal_response_clears_flag(self):
        """10. CTVE modal response resolves clarification and clears ctve_triggered flag."""
        issue_id = ObjectId()
        db.issues.insert_one({
            "_id": issue_id,
            "issue_id": f"SC-CTVE-{str(issue_id)[:6]}",
            "citizen_id": ObjectId(self.citizen_id),
            "status": "submitted",
            "category": "road",
            "ward": self.ward,
            "ctve_triggered": True,
            "ctve_message": "Photo is blurry. Please confirm or provide a clearer photo."
        })
        self.created_issue_ids.append(issue_id)

        resp = self.client.post(
            f"/api/issues/{issue_id}/ctve-response",
            json={"ctve_response": "confirm_details"},
            headers={"Authorization": f"Bearer {self.citizen_token}"}
        )
        self.assertEqual(resp.status_code, 200, resp.get_json())
        updated = db.issues.find_one({"_id": issue_id})
        self.assertFalse(updated.get("ctve_triggered", True))
        self.assertIsNone(updated.get("ctve_message"))


if __name__ == "__main__":
    unittest.main()
