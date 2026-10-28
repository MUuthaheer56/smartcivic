"""End-to-end complaint intake, officer retrieval, and persistence coverage."""

import unittest
from unittest.mock import patch

from bson import ObjectId

from app import create_app, db
from routes.auth import generate_tokens


class TestComplaintWorkflow(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        self.resident_id = ObjectId()
        self.officer_id = ObjectId()
        self.ward = f"Test Ward {ObjectId()}"
        db.users.insert_many([
            {
                "_id": self.resident_id,
                "email": f"resident-{self.resident_id}@test.invalid",
                "role": "resident",
                "ward": self.ward,
                "verified": True,
                "verification_status": "verified",
            },
            {
                "_id": self.officer_id,
                "email": f"officer-{self.officer_id}@test.invalid",
                "role": "officer",
                "ward": self.ward,
            },
        ])
        with self.app.app_context():
            self.resident_token, _ = generate_tokens(str(self.resident_id), "resident", self.ward)
            self.officer_token, _ = generate_tokens(str(self.officer_id), "officer", self.ward)
        self.created_issue_id = None

    def tearDown(self):
        if self.created_issue_id:
            issue = db.issues.find_one({"_id": self.created_issue_id})
            if issue and issue.get("cluster_id"):
                cluster_id = issue["cluster_id"]
                try:
                    db.clusters.delete_one({"_id": ObjectId(str(cluster_id))})
                except Exception:
                    pass
            db.issues.delete_one({"_id": self.created_issue_id})
            db.audit_logs.delete_many({"entity_id": str(self.created_issue_id)})
        db.users.delete_many({"_id": {"$in": [self.resident_id, self.officer_id]}})

    def test_submit_retrieve_and_restart_preserves_priority_trace(self):
        text_analysis = {
            "category": "road", "type": "pothole", "severity": "high",
            "department": "roads", "confidence": 0.9, "provider": "test",
        }
        final_prediction = dict(text_analysis)
        with (
            patch("services.complaint_service.ai_service.detect_and_translate", return_value={
                "detected_language": "english", "translated_text": "A deep pothole is damaging vehicles on the road."
            }),
            patch("services.complaint_service.ai_service.analyze_complaint_text", return_value=text_analysis),
            patch("services.complaint_service.ai_service.fuse_complaint_predictions", return_value=final_prediction),
            patch("services.complaint_service.ai_service.detect_duplicates", return_value=[]),
            patch("services.ai_pipeline.enqueue_ai_analysis"),
        ):
            response = self.client.post(
                "/api/issues",
                json={
                    "title": "Deep pothole",
                    "description": "A deep pothole is damaging vehicles on the road.",
                    "category": "road",
                    "type": "pothole",
                    "latitude": 12.9716,
                    "longitude": 77.5946,
                    "address": "Test Complaint Address",
                    "ward": self.ward,
                },
                headers={"Authorization": f"Bearer {self.resident_token}"},
            )

        self.assertEqual(response.status_code, 201, response.get_json())
        submitted = response.get_json()
        self.created_issue_id = ObjectId(submitted["data"]["_id"])
        stored = db.issues.find_one({"_id": self.created_issue_id})
        self.assertIsNotNone(stored)
        self.assertEqual(stored["status"], "submitted")
        self.assertGreater(stored["priority_score"], 0)
        self.assertEqual(stored["priority_decision"]["model_version"], "evidence-aware-v1")
        self.assertEqual(stored["priority_decision"]["input_features"]["location_available"], True)
        self.assertIn("image", stored["missing_evidence"])

        response = self.client.get(
            f"/api/issues/{stored['issue_id']}",
            headers={"Authorization": f"Bearer {self.officer_token}"},
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["data"]["priority_score"], stored["priority_score"])

        response = self.client.post(
            f"/api/issues/{stored['_id']}/priority",
            json={"score": 61.5, "reason": "Officer confirmed active traffic hazard."},
            headers={"Authorization": f"Bearer {self.officer_token}"},
        )
        self.assertEqual(response.status_code, 200, response.get_json())

        restarted_app = create_app()
        restarted_client = restarted_app.test_client()
        response = restarted_client.get(
            f"/api/issues/{stored['issue_id']}",
            headers={"Authorization": f"Bearer {self.officer_token}"},
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        persisted = response.get_json()["data"]
        self.assertEqual(persisted["priority_decision"]["model_version"], "evidence-aware-v1")
        self.assertEqual(persisted["priority_score"], 61.5)
        self.assertEqual(persisted["priority_override"]["reason"], "Officer confirmed active traffic hazard.")


if __name__ == "__main__":
    unittest.main()