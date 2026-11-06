"""
tests/test_announcements.py - Unit & API Tests for Admin Announcement Broadcast Feature
Covers:
1. Admin broadcast (201 Created) with plain-text sanitation and audit trail.
2. Non-admin broadcast attempt rejected (403 Forbidden).
3. Plain text sanitation (HTML tags stripped, XSS payloads neutralized).
4. Idempotency key handling.
5. Audience and expiration filtering on GET /api/announcements/active.
6. Read tracking per user (POST /api/announcements/<id>/read) and read counts in admin view.
7. Retraction (POST /api/admin/announcements/<id>/retract) by admin only.
8. Audit log entries for broadcast and retraction.
"""

import unittest
from datetime import datetime, timedelta
from bson import ObjectId

from app import create_app, db
from routes.auth import generate_tokens


class TestAnnouncementsFeature(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.app.config["WTF_CSRF_ENABLED"] = False
        self.client = self.app.test_client()

        self.admin_id = ObjectId()
        self.citizen_id = ObjectId()
        self.worker_id = ObjectId()
        self.officer_id = ObjectId()

        db.users.insert_many([
            {
                "_id": self.admin_id,
                "email": f"admin_{self.admin_id}@test.com",
                "role": "admin",
                "ward": "ALL",
                "verified": True,
                "verification_status": "verified",
                "status": "active"
            },
            {
                "_id": self.citizen_id,
                "email": f"citizen_{self.citizen_id}@test.com",
                "role": "citizen",
                "ward": "Ward 150 - Bellandur",
                "verified": True,
                "verification_status": "verified",
                "status": "active"
            },
            {
                "_id": self.worker_id,
                "email": f"worker_{self.worker_id}@test.com",
                "role": "worker",
                "ward": "Ward 150 - Bellandur",
                "verified": True,
                "verification_status": "verified",
                "status": "active"
            },
            {
                "_id": self.officer_id,
                "email": f"officer_{self.officer_id}@test.com",
                "role": "officer",
                "ward": "Ward 150 - Bellandur",
                "verified": True,
                "verification_status": "verified",
                "status": "active"
            }
        ])

        with self.app.app_context():
            self.admin_token, _ = generate_tokens(str(self.admin_id), "admin", "ALL")
            self.citizen_token, _ = generate_tokens(str(self.citizen_id), "citizen", "Ward 150 - Bellandur")
            self.worker_token, _ = generate_tokens(str(self.worker_id), "worker", "Ward 150 - Bellandur")
            self.officer_token, _ = generate_tokens(str(self.officer_id), "officer", "Ward 150 - Bellandur")

        self.created_announcements = []

    def tearDown(self):
        if self.created_announcements:
            db.announcements.delete_many({"_id": {"$in": self.created_announcements}})
            db.announcement_reads.delete_many({"announcement_id": {"$in": self.created_announcements}})
            db.audit_logs.delete_many({"entity_id": {"$in": [str(a) for a in self.created_announcements]}})
        db.users.delete_many({"_id": {"$in": [self.admin_id, self.citizen_id, self.worker_id, self.officer_id]}})

    def test_admin_broadcast_success_and_audit(self):
        """Admin can broadcast announcement, creating doc and audit log entry."""
        payload = {
            "title": "Scheduled Water Pipeline Maintenance",
            "body": "Water supply will be suspended in Ward 150 between 10 AM and 4 PM tomorrow.",
            "severity": "warning",
            "audience": "both",
            "pinned": True,
            "expires_in_hours": 48
        }
        resp = self.client.post(
            "/api/admin/announcements",
            json=payload,
            headers={"Authorization": f"Bearer {self.admin_token}"}
        )
        self.assertEqual(resp.status_code, 201, resp.get_json())
        data = resp.get_json()
        self.assertTrue(data["success"])
        ann_id = ObjectId(data["announcement"]["_id"])
        self.created_announcements.append(ann_id)

        # Check DB doc
        doc = db.announcements.find_one({"_id": ann_id})
        self.assertIsNotNone(doc)
        self.assertEqual(doc["title"], payload["title"])
        self.assertEqual(doc["severity"], "warning")
        self.assertEqual(doc["audience"], "both")
        self.assertTrue(doc["pinned"])
        self.assertEqual(doc["status"], "active")

        # Check Audit Log
        audit = db.audit_logs.find_one({"entity_id": ObjectId(ann_id), "action": "ADMIN_ANNOUNCEMENT_BROADCAST"})
        self.assertIsNotNone(audit, "Audit log must be created for announcement broadcast")

    def test_non_admin_cannot_broadcast(self):
        """Citizen, worker, or officer cannot broadcast announcements (403 Forbidden)."""
        payload = {"title": "Unauthorized Title", "body": "Unauthorized announcement body."}
        for token in [self.citizen_token, self.worker_token, self.officer_token]:
            resp = self.client.post(
                "/api/admin/announcements",
                json=payload,
                headers={"Authorization": f"Bearer {token}"}
            )
            self.assertEqual(resp.status_code, 403)

    def test_html_and_xss_stripped(self):
        """HTML tags and script injection payloads are stripped from title and body."""
        payload = {
            "title": "Alert <script>alert('xss')</script><b>Important</b>",
            "body": "<img src=x onerror=alert(1)>Emergency notice: Please take note <i>immediately</i>.",
            "severity": "critical"
        }
        resp = self.client.post(
            "/api/admin/announcements",
            json=payload,
            headers={"Authorization": f"Bearer {self.admin_token}"}
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()["announcement"]
        ann_id = ObjectId(data["_id"])
        self.created_announcements.append(ann_id)

        self.assertNotIn("<script>", data["title"])
        self.assertNotIn("<b>", data["title"])
        self.assertNotIn("<img", data["body"])
        self.assertNotIn("<i>", data["body"])
        self.assertIn("Alert alert('xss')Important", data["title"])
        self.assertIn("Emergency notice: Please take note immediately.", data["body"])

    def test_idempotency_key(self):
        """Repeated submission with identical idempotency_key returns original announcement without duplicates."""
        key = f"idemp_{ObjectId()}"
        payload = {
            "title": "Idempotent Announcement",
            "body": "Body for testing idempotent broadcast.",
            "idempotency_key": key
        }

        # 1st call
        r1 = self.client.post(
            "/api/admin/announcements",
            json=payload,
            headers={"Authorization": f"Bearer {self.admin_token}"}
        )
        self.assertEqual(r1.status_code, 201)
        ann_id = ObjectId(r1.get_json()["announcement"]["_id"])
        self.created_announcements.append(ann_id)

        # 2nd call
        r2 = self.client.post(
            "/api/admin/announcements",
            json=payload,
            headers={"Authorization": f"Bearer {self.admin_token}"}
        )
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.get_json()["announcement"]["_id"], str(ann_id))

        count = db.announcements.count_documents({"idempotency_key": key})
        self.assertEqual(count, 1)

    def test_audience_and_expiry_filtering(self):
        """Audience filtering separates citizen vs worker, and expired announcements are excluded."""
        now = datetime.utcnow()
        # 1. Citizen-only announcement
        c_ann = ObjectId()
        db.announcements.insert_one({
            "_id": c_ann,
            "title": "Citizen Only Alert",
            "body": "Special alert for citizens only.",
            "audience": "citizen",
            "severity": "info",
            "status": "active",
            "expires_at": now + timedelta(days=1),
            "created_at": now
        })
        self.created_announcements.append(c_ann)

        # 2. Worker-only announcement
        w_ann = ObjectId()
        db.announcements.insert_one({
            "_id": w_ann,
            "title": "Worker Safety Protocol",
            "body": "Special alert for field workers.",
            "audience": "worker",
            "severity": "warning",
            "status": "active",
            "expires_at": now + timedelta(days=1),
            "created_at": now
        })
        self.created_announcements.append(w_ann)

        # 3. Expired announcement
        exp_ann = ObjectId()
        db.announcements.insert_one({
            "_id": exp_ann,
            "title": "Expired Alert",
            "body": "This alert has passed its expiry.",
            "audience": "both",
            "severity": "info",
            "status": "active",
            "expires_at": now - timedelta(hours=1),
            "created_at": now - timedelta(days=2)
        })
        self.created_announcements.append(exp_ann)

        # Citizen view
        c_resp = self.client.get(
            "/api/announcements/active",
            headers={"Authorization": f"Bearer {self.citizen_token}"}
        )
        self.assertEqual(c_resp.status_code, 200)
        c_ids = [a["_id"] for a in c_resp.get_json()["data"]]
        self.assertIn(str(c_ann), c_ids)
        self.assertNotIn(str(w_ann), c_ids)
        self.assertNotIn(str(exp_ann), c_ids)

        # Worker view
        w_resp = self.client.get(
            "/api/announcements/active",
            headers={"Authorization": f"Bearer {self.worker_token}"}
        )
        self.assertEqual(w_resp.status_code, 200)
        w_ids = [a["_id"] for a in w_resp.get_json()["data"]]
        self.assertIn(str(w_ann), w_ids)
        self.assertNotIn(str(c_ann), w_ids)
        self.assertNotIn(str(exp_ann), w_ids)

    def test_mark_as_read_and_admin_counts(self):
        """User can mark announcement as read, setting is_read=True and incrementing admin read count."""
        now = datetime.utcnow()
        ann_id = ObjectId()
        db.announcements.insert_one({
            "_id": ann_id,
            "title": "Read Tracking Test",
            "body": "Testing read status tracking.",
            "audience": "both",
            "severity": "info",
            "status": "active",
            "expires_at": now + timedelta(days=1),
            "created_at": now
        })
        self.created_announcements.append(ann_id)

        # Before read
        resp1 = self.client.get(
            "/api/announcements/active",
            headers={"Authorization": f"Bearer {self.citizen_token}"}
        )
        item1 = next(a for a in resp1.get_json()["data"] if a["_id"] == str(ann_id))
        self.assertFalse(item1["is_read"])

        # Mark read
        r_post = self.client.post(
            f"/api/announcements/{ann_id}/read",
            headers={"Authorization": f"Bearer {self.citizen_token}"}
        )
        self.assertEqual(r_post.status_code, 200)

        # After read
        resp2 = self.client.get(
            "/api/announcements/active",
            headers={"Authorization": f"Bearer {self.citizen_token}"}
        )
        item2 = next(a for a in resp2.get_json()["data"] if a["_id"] == str(ann_id))
        self.assertTrue(item2["is_read"])

        # Check in admin view
        admin_resp = self.client.get(
            "/api/admin/announcements",
            headers={"Authorization": f"Bearer {self.admin_token}"}
        )
        self.assertEqual(admin_resp.status_code, 200)
        admin_item = next(a for a in admin_resp.get_json()["data"] if a["_id"] == str(ann_id))
        self.assertGreaterEqual(admin_item.get("read_count", 0), 1)

    def test_retract_announcement(self):
        """Admin can retract announcement, removing it from active list and logging audit entry."""
        now = datetime.utcnow()
        ann_id = ObjectId()
        db.announcements.insert_one({
            "_id": ann_id,
            "title": "To Be Retracted",
            "body": "This announcement will be retracted shortly.",
            "audience": "both",
            "severity": "warning",
            "status": "active",
            "expires_at": now + timedelta(days=1),
            "created_at": now
        })
        self.created_announcements.append(ann_id)

        # Retract
        ret_resp = self.client.post(
            f"/api/admin/announcements/{ann_id}/retract",
            headers={"Authorization": f"Bearer {self.admin_token}"}
        )
        self.assertEqual(ret_resp.status_code, 200)

        # Verify not in active
        active_resp = self.client.get(
            "/api/announcements/active",
            headers={"Authorization": f"Bearer {self.citizen_token}"}
        )
        active_ids = [a["_id"] for a in active_resp.get_json()["data"]]
        self.assertNotIn(str(ann_id), active_ids)

        # Check DB status
        doc = db.announcements.find_one({"_id": ann_id})
        self.assertEqual(doc["status"], "retracted")

        # Check audit log
        audit = db.audit_logs.find_one({"entity_id": ObjectId(ann_id), "action": "ADMIN_ANNOUNCEMENT_RETRACTED"})
        self.assertIsNotNone(audit)


if __name__ == "__main__":
    unittest.main()
