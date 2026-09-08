"""
SmartCivic — Complaint Unit & Validation Tests
Tests complaint creation, image validation, and payload length enforcement.
"""
import unittest
import io
from app import create_app, db
from utils.validators import validate_complaint, validate_image, ValidationError
from routes.auth import generate_tokens, hash_password
from bson import ObjectId

class TestComplaint(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        self.citizen_id = ObjectId()
        db.users.insert_one({"_id": self.citizen_id, "email": "test_comp_cit@smartcivic.com", "password_hash": hash_password("pass"), "role": "resident"})
        with self.app.app_context():
            self.tok, _ = generate_tokens(str(self.citizen_id), "citizen", "Ward 1")

    def tearDown(self):
        db.users.delete_one({"_id": self.citizen_id})
        db.issues.delete_many({"address": "Test Complaint Address"})

    def test_missing_description_returns_400(self):
        data = {"latitude": 12.97, "longitude": 77.59}
        with self.assertRaises(ValidationError) as ctx:
            validate_complaint(data)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_short_description_returns_400(self):
        data = {"description": "too short", "latitude": 12.97, "longitude": 77.59}
        with self.assertRaises(ValidationError) as ctx:
            validate_complaint(data)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_non_image_upload_returns_400(self):
        file_obj = io.BytesIO(b"Hello world text file content")
        file_obj.filename = "test.txt"
        with self.assertRaises(ValidationError) as ctx:
            validate_image(file_obj)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_oversized_image_returns_400(self):
        file_obj = io.BytesIO(b"0" * (11 * 1024 * 1024)) # 11MB
        file_obj.filename = "large.jpg"
        with self.assertRaises(ValidationError) as ctx:
            validate_image(file_obj)
        self.assertEqual(ctx.exception.status_code, 400)

if __name__ == "__main__":
    unittest.main()
