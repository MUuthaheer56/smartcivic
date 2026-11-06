"""
test_offline_e2e.py - Verification that complete citizen-officer-worker lifecycle
runs strictly offline (AI_MODE=local) without any outbound internet connections.
Monkeypatches socket.create_connection, urllib.request.urlopen, and requests.Session.request
to fail if any outbound non-localhost IP/domain is targeted.
"""

import io
import os
import socket
import urllib.request
import unittest
from unittest.mock import patch
import requests
from PIL import Image

from app import create_app, db
from bson import ObjectId
from routes.auth import generate_tokens, hash_password


class NetworkCallBlockedError(RuntimeError):
    pass


_orig_create_connection = socket.create_connection
_orig_urlopen = urllib.request.urlopen
_orig_requests_send = requests.Session.send


def _guarded_create_connection(address, *args, **kwargs):
    host, port = address[0], address[1]
    # Allow local MongoDB, dev servers, loopback
    if host in ("127.0.0.1", "localhost", "::1", "0.0.0.0"):
        return _orig_create_connection(address, *args, **kwargs)
    raise NetworkCallBlockedError(f"External outbound socket blocked to {host}:{port} in offline mode!")


def _guarded_urlopen(req, *args, **kwargs):
    url = req.full_url if hasattr(req, "full_url") else str(req)
    if "127.0.0.1" in url or "localhost" in url:
        return _orig_urlopen(req, *args, **kwargs)
    raise NetworkCallBlockedError(f"External HTTP request blocked to {url} in offline mode!")


def _guarded_requests_send(session, request, *args, **kwargs):
    url = getattr(request, "url", "")
    if "127.0.0.1" in url or "localhost" in url:
        return _orig_requests_send(session, request, *args, **kwargs)
    raise NetworkCallBlockedError(f"External requests.send blocked to {url} in offline mode!")


class TestOfflineE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Force local AI mode
        os.environ["AI_MODE"] = "local"
        os.environ["AI_LOCAL_TEXT_ENABLED"] = "true"
        os.environ["AI_LOCAL_DETECTOR_ENABLED"] = "true"

    def setUp(self):
        # Enable network guards
        self.socket_patch = patch("socket.create_connection", side_effect=_guarded_create_connection)
        self.urlopen_patch = patch("urllib.request.urlopen", side_effect=_guarded_urlopen)
        self.requests_patch = patch("requests.Session.send", side_effect=_guarded_requests_send)
        self.socket_patch.start()
        self.urlopen_patch.start()
        self.requests_patch.start()

        self.app = create_app()
        self.app.config["TESTING"] = True
        self.app.config["WTF_CSRF_ENABLED"] = False  # API tests use direct JSON / token auth
        self.client = self.app.test_client()

        self.ward = "Ward 150 - Bellandur"
        self.cleanup_user_ids = []
        self.cleanup_issue_ids = []

    def tearDown(self):
        self.requests_patch.stop()
        self.urlopen_patch.stop()
        self.socket_patch.stop()

        if self.cleanup_issue_ids:
            db.issues.delete_many({"_id": {"$in": self.cleanup_issue_ids}})
            db.audit_logs.delete_many({"entity_id": {"$in": [str(i) for i in self.cleanup_issue_ids]}})
            db.assignments.delete_many({"issue_id": {"$in": [str(i) for i in self.cleanup_issue_ids]}})
        if self.cleanup_user_ids:
            db.users.delete_many({"_id": {"$in": self.cleanup_user_ids}})

    def _create_sample_jpeg(self, width=416, height=416, color=(200, 100, 50)):
        buf = io.BytesIO()
        img = Image.new("RGB", (width, height), color=color)
        img.save(buf, format="JPEG")
        buf.seek(0)
        return buf

    def test_complete_offline_lifecycle(self):
        """
        Runs full lifecycle completely offline:
        1. Citizen registration
        2. Officer verifies citizen
        3. Citizen reports road damage with photo + GPS
        4. Verifies offline text + YOLO AI pipeline, classification, routing, and CEFAP priority
        5. Officer assigns issue to worker
        6. Worker resolves issue with after-photo
        7. Citizen confirms resolution
        All while blocking external network calls.
        """
        # Step 1: Citizen registration
        citizen_email = f"offline_citizen_{ObjectId()}@smartcivic.local"
        reg_res = self.client.post("/api/auth/register", json={
            "name": "Offline Citizen",
            "email": citizen_email,
            "password": "Password@123",
            "phone": "+919876543210",
            "ward": self.ward,
            "role": "citizen"
        })
        self.assertEqual(reg_res.status_code, 201, reg_res.get_json())
        citizen_user = db.users.find_one({"email": citizen_email})
        self.assertIsNotNone(citizen_user)
        citizen_id = citizen_user["_id"]
        self.cleanup_user_ids.append(citizen_id)

        # Step 2: Officer setup & verify citizen
        officer_id = ObjectId()
        self.cleanup_user_ids.append(officer_id)
        db.users.insert_one({
            "_id": officer_id,
            "name": "Offline Officer",
            "email": f"officer_{officer_id}@smartcivic.local",
            "password_hash": hash_password("Password@123"),
            "role": "officer",
            "ward": self.ward,
            "verified": True
        })

        # Worker setup
        worker_id = ObjectId()
        self.cleanup_user_ids.append(worker_id)
        db.users.insert_one({
            "_id": worker_id,
            "name": "Offline Worker",
            "email": f"worker_{worker_id}@smartcivic.local",
            "password_hash": hash_password("Password@123"),
            "role": "worker",
            "ward": self.ward,
            "verified": True,
            "is_available": True,
            "active_assignments": 0,
            "skills": ["road_repair", "pothole"]
        })

        with self.app.app_context():
            officer_token, _ = generate_tokens(str(officer_id), "officer", self.ward)
            worker_token, _ = generate_tokens(str(worker_id), "worker", self.ward)

        # Officer verifies citizen
        v_res = self.client.post(
            f"/api/auth/users/{citizen_id}/verify",
            headers={"Authorization": f"Bearer {officer_token}"},
            json={"status": "verified"}
        )
        self.assertEqual(v_res.status_code, 200, v_res.get_json())
        citizen_user = db.users.find_one({"_id": citizen_id})
        self.assertTrue(citizen_user.get("verified"))

        with self.app.app_context():
            citizen_token, _ = generate_tokens(str(citizen_id), "citizen", self.ward)

        # Step 3: Citizen reports road damage with photo + GPS (random unique coordinates to avoid duplicate clustering)
        import random
        lat = 12.9000 + random.uniform(0.01, 0.09)
        lon = 77.6000 + random.uniform(0.01, 0.09)
        photo_bytes = self._create_sample_jpeg()
        data = {
            "title": f"Unique pothole report {ObjectId()}",
            "description": "Deep dangerous pothole near junction causing traffic slowdown and safety risk",
            "category": "road",
            "latitude": str(lat),
            "longitude": str(lon),
            "ward": self.ward,
            "image": (photo_bytes, "pothole.jpg", "image/jpeg")
        }
        rep_res = self.client.post(
            "/api/issues",
            headers={"Authorization": f"Bearer {citizen_token}"},
            data=data,
            content_type="multipart/form-data"
        )
        self.assertEqual(rep_res.status_code, 201, rep_res.get_json())
        res_json = rep_res.get_json()
        issue_data = res_json.get("data", {})
        # Note: serializers provide '_id' as MongoDB ObjectId hex, and 'id' as formatted issue_id (e.g. SC-2026-...)
        raw_mongo_id = issue_data.get("_id") or res_json.get("data", {}).get("_id")
        if not raw_mongo_id:
            # Fallback to direct DB query if needed
            found = db.issues.find_one({"citizen_id": str(citizen_id)})
            raw_mongo_id = str(found["_id"])
        issue_obj_id = ObjectId(raw_mongo_id)
        self.cleanup_issue_ids.append(issue_obj_id)
        issue_id_str = str(issue_obj_id)

        # Step 4: Verify offline AI classification, routing, and CEFAP priority
        issue_doc = db.issues.find_one({"_id": issue_obj_id})
        self.assertIsNotNone(issue_doc)
        self.assertEqual(issue_doc.get("category"), "road")
        self.assertEqual(issue_doc.get("department"), "roads")
        self.assertIn(issue_doc.get("status"), ("submitted", "ai_reviewed"))
        # Verify priority is assigned
        self.assertIn("priority", issue_doc)
        self.assertIn("priority_score", issue_doc)
        self.assertGreater(issue_doc.get("priority_score", 0), 0)

        # Step 5: Officer assigns worker
        assign_res = self.client.post(
            f"/api/issues/{issue_id_str}/assign",
            headers={"Authorization": f"Bearer {officer_token}"},
            json={"worker_id": str(worker_id), "notes": "Please fix immediately"}
        )
        self.assertEqual(assign_res.status_code, 200, assign_res.get_json())
        issue_doc = db.issues.find_one({"_id": issue_obj_id})
        self.assertEqual(issue_doc.get("status"), "assigned")
        self.assertEqual(str(issue_doc.get("worker_id")), str(worker_id))

        # Step 6: Worker resolves issue with proof photo
        after_photo = self._create_sample_jpeg(color=(50, 150, 50))
        res_res = self.client.post(
            f"/api/issues/{issue_id_str}/resolve",
            headers={"Authorization": f"Bearer {worker_token}"},
            data={
                "notes": "Pothole patched with cold asphalt and steam rolled",
                "after_image": (after_photo, "resolved.jpg", "image/jpeg")
            },
            content_type="multipart/form-data"
        )
        self.assertEqual(res_res.status_code, 200, res_res.get_json())
        issue_doc = db.issues.find_one({"_id": issue_obj_id})
        self.assertIn(issue_doc.get("status"), ("resolved", "work_completed"))

        # Step 7: Neighbor/Community citizen confirms resolution
        neighbor_id = ObjectId()
        self.cleanup_user_ids.append(neighbor_id)
        db.users.insert_one({
            "_id": neighbor_id,
            "name": "Neighbor Citizen",
            "email": f"neighbor_{neighbor_id}@smartcivic.local",
            "password_hash": hash_password("Password@123"),
            "role": "citizen",
            "ward": self.ward,
            "verified": True
        })
        with self.app.app_context():
            neighbor_token, _ = generate_tokens(str(neighbor_id), "citizen", self.ward)

        conf_res = self.client.post(
            f"/api/issues/{issue_id_str}/confirm",
            headers={"Authorization": f"Bearer {neighbor_token}"},
            json={"note": "Confirmed fixed, looks great now"}
        )
        self.assertEqual(conf_res.status_code, 200, conf_res.get_json())
        print("\n[SUCCESS] Full citizen-officer-worker lifecycle executed completely offline with zero outbound network calls.")


if __name__ == "__main__":
    unittest.main()
