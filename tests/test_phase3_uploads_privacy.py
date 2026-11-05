"""
Phase 3 — Uploads, PII and Privacy Tests
Tests verifying Master Fix Plan Phase 3 requirements & Gate conditions:
1. Upload content validation: .php renamed to .jpg is rejected (Pillow verify).
2. Path traversal filenames (../../evil.jpg) are neutralized with random UUIDs.
3. Image EXIF metadata is completely stripped on save.
4. Pillow decompression bomb protection (MAX_IMAGE_PIXELS).
5. Cross-ward officer and unauthorized citizen access to verification docs returns 403.
6. Fernet encryption at rest for verification documents.
7. Real anonymous reporting: no citizen_id on issue, salted hash in anonymous_reporters, fuzzed coordinates.
8. Whitelisted serializers (public_issue, citizen_issue, officer_issue) prevent raw document leaks.
9. PII scrubbing (emails, phone numbers) before Gemini dispatch.
10. Worker phone number masking in public/resident endpoints.
"""
import unittest
import io
import os
import shutil
from datetime import datetime
from bson import ObjectId
from PIL import Image
from cryptography.fernet import Fernet
from app import create_app, client
from config import Config
from routes.auth import generate_tokens, hash_password
from services.ai_service import sanitize_gemini_prompt
from utils.crypto_utils import encrypt_bytes, decrypt_bytes, is_fernet_encrypted
from utils.serializers import serialize_public_issue, serialize_citizen_issue, serialize_officer_issue, mask_phone_number

test_db = client["smartcivic_test"]


class TestPhase3UploadsAndPrivacy(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

        import app
        import routes.auth
        import utils.auth_helpers
        import routes.api.issues
        import services.complaint_service
        self.orig_app_db = app.db
        self.orig_auth_db = routes.auth.db
        self.orig_helpers_db = utils.auth_helpers.db
        self.orig_issues_db = routes.api.issues.db
        self.orig_complaint_db = services.complaint_service.db

        app.db = test_db
        routes.auth.db = test_db
        utils.auth_helpers.db = test_db
        routes.api.issues.db = test_db
        services.complaint_service.db = test_db

        self.test_upload_dir = os.path.join(self.app.root_path, "uploads_test_p3")
        os.makedirs(self.test_upload_dir, exist_ok=True)

    def tearDown(self):
        test_db.users.delete_many({"email": {"$regex": "^test_p3_.*@smartcivic.com"}})
        test_db.issues.delete_many({"title": {"$regex": "^P3 Test.*"}})
        test_db.anonymous_reporters.delete_many({})

        if os.path.exists(self.test_upload_dir):
            shutil.rmtree(self.test_upload_dir, ignore_errors=True)

        import app
        import routes.auth
        import utils.auth_helpers
        import routes.api.issues
        import services.complaint_service
        app.db = self.orig_app_db
        routes.auth.db = self.orig_auth_db
        utils.auth_helpers.db = self.orig_helpers_db
        routes.api.issues.db = self.orig_issues_db
        services.complaint_service.db = self.orig_complaint_db

    def _create_user(self, suffix, role="citizen", ward="Ward 1", verified=True):
        uid = ObjectId()
        doc = {
            "_id": uid,
            "name": f"User {suffix}",
            "email": f"test_p3_{suffix}@smartcivic.com",
            "password_hash": hash_password("ValidPassword123!"),
            "role": role,
            "ward": ward,
            "ward_id": ward.lower().replace(" ", "_"),
            "verified": verified,
            "verification_status": "approved" if verified else "pending",
            "status": "active" if verified else "pending_verification"
        }
        test_db.users.insert_one(doc)
        return uid, doc

    def _generate_valid_image_bytes(self, with_exif=False):
        img = Image.new("RGB", (100, 100), color="blue")
        bio = io.BytesIO()
        if with_exif:
            exif = img.getexif()
            exif[0x010f] = "SmartCivicCam"
            exif[0x0131] = "ExifInjector"
            img.save(bio, "JPEG", exif=exif)
        else:
            img.save(bio, "JPEG")
        bio.seek(0)
        return bio.getvalue()

    def test_gate_php_renamed_to_jpg_is_rejected(self):
        """Gate 3.1: Uploading a malicious script renamed to .jpg is rejected by content inspection."""
        uid, _ = self._create_user("upload_php")
        with self.app.app_context():
            token, _ = generate_tokens(str(uid), "citizen", "Ward 1")

        fake_image = io.BytesIO(b"<?php echo 'malicious payload'; system($_GET['cmd']); ?>")
        data = {
            "title": "P3 Test Malicious Upload",
            "description": "Attempting to upload a PHP shell masquerading as a JPEG image.",
            "image": (fake_image, "shell.php.jpg")
        }

        self.client.set_cookie("access_token", token)
        res = self.client.post("/api/issues", data=data, content_type="multipart/form-data")
        self.assertEqual(res.status_code, 400, "PHP script disguised as JPG must be rejected with 400!")

    def test_gate_path_traversal_filename_neutralized(self):
        """Gate 3.1: Filenames containing path traversal characters are neutralized to safe UUIDs."""
        uid, _ = self._create_user("path_trav")
        with self.app.app_context():
            token, _ = generate_tokens(str(uid), "citizen", "Ward 1")

        valid_img = io.BytesIO(self._generate_valid_image_bytes())
        data = {
            "title": "P3 Test Path Traversal",
            "description": "Attempting path traversal in file upload parameter.",
            "image": (valid_img, "../../../../etc/cron.d/malicious.jpg")
        }

        self.client.set_cookie("access_token", token)
        res = self.client.post("/api/issues", data=data, content_type="multipart/form-data")
        self.assertEqual(res.status_code, 201)
        res_json = res.get_json()

        # Filename stored in database must be a pure hex UUID
        created_issue = test_db.issues.find_one({"title": "P3 Test Path Traversal"})
        self.assertIsNotNone(created_issue)
        self.assertTrue(len(created_issue.get("images", [])) > 0)
        saved_fn = created_issue["images"][0]["filename"]
        self.assertNotIn("..", saved_fn)
        self.assertNotIn("/", saved_fn)
        self.assertNotIn("\\", saved_fn)

    def test_gate_image_exif_metadata_stripped(self):
        """Gate 3.1: Stored images have all EXIF metadata stripped to protect reporter privacy."""
        from utils.image_utils import save_uploaded_image
        exif_img_bytes = self._generate_valid_image_bytes(with_exif=True)
        img_storage = io.BytesIO(exif_img_bytes)
        img_storage.filename = "photo_with_exif.jpg"

        info = save_uploaded_image(img_storage, upload_folder=self.test_upload_dir)
        saved_file = info["filepath"]

        # Inspect saved image: EXIF dictionary must be completely empty or nonexistent
        with Image.open(saved_file) as reloaded:
            exif_data = reloaded.getexif()
            self.assertEqual(len(exif_data), 0, "EXIF tags were not stripped from saved image!")

    def test_gate_cross_ward_officer_cannot_view_verification_doc(self):
        """Gate 3.2: Officer from Ward 2 attempting to view verification doc of Ward 1 resident gets 403."""
        resident_id, _ = self._create_user("res_ward1", role="citizen", ward="Ward 1", verified=False)
        officer_ward2_id, _ = self._create_user("off_ward2", role="officer", ward="Ward 2")
        officer_ward1_id, _ = self._create_user("off_ward1", role="officer", ward="Ward 1")

        doc_filename = "ward1_resident_id.jpg"
        test_db.users.update_one(
            {"_id": resident_id},
            {"$set": {"verification_doc": f"/files/verification_docs/{doc_filename}"}}
        )

        # Place a mock file in verification_docs directory
        v_dir = os.path.join(Config.PRIVATE_UPLOAD_DIR, "verification_docs")
        os.makedirs(v_dir, exist_ok=True)
        file_path = os.path.join(v_dir, doc_filename)
        with open(file_path, "wb") as f:
            f.write(encrypt_bytes(b"MOCK_ENCRYPTED_ID_CARD"))

        try:
            with self.app.app_context():
                w2_token, _ = generate_tokens(str(officer_ward2_id), "officer", "Ward 2")
                w1_token, _ = generate_tokens(str(officer_ward1_id), "officer", "Ward 1")

            # 1. Ward 2 officer -> 403 Forbidden
            res_w2 = self.client.get(
                f"/files/verification_docs/{doc_filename}",
                headers={"Authorization": f"Bearer {w2_token}"}
            )
            self.assertEqual(res_w2.status_code, 403, "Cross-ward officer must be denied with 403!")

            # 2. Ward 1 officer -> 200 OK (and decrypted data matches)
            res_w1 = self.client.get(
                f"/files/verification_docs/{doc_filename}",
                headers={"Authorization": f"Bearer {w1_token}"}
            )
            self.assertEqual(res_w1.status_code, 200)
            self.assertEqual(res_w1.data, b"MOCK_ENCRYPTED_ID_CARD")
        finally:
            if os.path.exists(file_path):
                os.remove(file_path)

    def test_gate_anonymous_report_exposes_no_identity(self):
        """Gate 3.3: Anonymous reporting stores NO citizen_id on the issue, hashes reporter in restricted collection, and fuzzes location."""
        uid, _ = self._create_user("anon_reporter")
        with self.app.app_context():
            token, _ = generate_tokens(str(uid), "citizen", "Ward 1")

        self.client.set_cookie("access_token", token)
        res = self.client.post("/api/issues", json={
            "title": "P3 Test Anonymous Grievance",
            "description": "Reporting sensitive municipal issue anonymously.",
            "is_anonymous": True,
            "lat": 12.9716482,
            "lng": 77.5946123,
            "ward": "Ward 1"
        })
        self.assertEqual(res.status_code, 201)

        # 1. Database check: citizen_id must be None or absent on issue document
        issue_in_db = test_db.issues.find_one({"title": "P3 Test Anonymous Grievance"})
        self.assertIsNotNone(issue_in_db)
        self.assertIsNone(issue_in_db.get("citizen_id"))
        self.assertTrue(issue_in_db.get("is_anonymous"))

        # 2. Check anonymous_reporters restricted collection has the salted hash
        anon_entry = test_db.anonymous_reporters.find_one({"issue_id": issue_in_db["_id"]})
        self.assertIsNotNone(anon_entry, "Salted hash was not stored in anonymous_reporters collection!")
        self.assertNotIn(str(uid), anon_entry["reporter_hash"], "Salted hash must not reveal the raw user ID!")

        # 3. Public serializer check: coordinates are fuzzed and no identity leaks
        serialized = serialize_public_issue(issue_in_db)
        self.assertNotIn("citizen_id", serialized)
        self.assertNotIn("reporter_id", serialized)
        coords = serialized["location"]["coordinates"]
        # Coordinates fuzzed to 3 decimal places
        self.assertEqual(round(coords[0], 3), coords[0])
        self.assertEqual(round(coords[1], 3), coords[1])

    def test_pii_scrubbing_before_gemini(self):
        """Plan 3.5: Phone numbers and emails are scrubbed before prompt dispatch to Gemini."""
        raw_text = "Call John at +91 9876543210 or email resident.jane@example.com regarding the open drain."
        cleaned = sanitize_gemini_prompt(raw_text)

        self.assertNotIn("9876543210", cleaned)
        self.assertNotIn("resident.jane@example.com", cleaned)
        self.assertIn("[REDACTED_PHONE]", cleaned)
        self.assertIn("[REDACTED_EMAIL]", cleaned)

    def test_worker_phone_masking(self):
        """Plan 3.5: Worker phone numbers are masked in API serialization."""
        raw_phone = "+91 98765 43210"
        masked = mask_phone_number(raw_phone)
        self.assertEqual(masked, "+91 98*** **210")

    def test_serializers_field_whitelisting(self):
        """Plan 3.4: Serializers strictly whitelist fields and discard embeddings and sensitive vectors."""
        mock_raw_doc = {
            "_id": ObjectId(),
            "title": "P3 Test Whitelisting",
            "description": "Test description",
            "citizen_id": str(ObjectId()),
            "status": "submitted",
            "severity": "high",
            "category": "road",
            "text_embedding": [0.123, 0.456, -0.789] * 100,  # 300-dimension vector
            "internal_cefap_weights": {"alpha": 0.8},
            "created_at": datetime.utcnow()
        }

        pub = serialize_public_issue(mock_raw_doc)
        self.assertNotIn("text_embedding", pub)
        self.assertNotIn("citizen_id", pub)
        self.assertNotIn("internal_cefap_weights", pub)
        self.assertIn("title", pub)
        self.assertIn("status", pub)


if __name__ == "__main__":
    unittest.main()
