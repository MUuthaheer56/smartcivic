"""
SmartCivic — Assignment Service Unit Tests
Tests worker skill matching, recommendation filters, and assignment persistence.
"""
import unittest
from app import create_app, db
from services.assignment_service import get_required_worker_skills, assign_worker, recommend_workers
from routes.auth import generate_tokens, hash_password
from bson import ObjectId

class TestAssignment(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.worker_id = ObjectId()
        self.officer_id = ObjectId()
        self.issue_id = ObjectId()
        
        db.users.delete_many({"email": {"$in": ["wrk_b@smartcivic.com", "off_b@smartcivic.com"]}})
        db.users.insert_one({"_id": self.worker_id, "name": "Worker B", "email": "wrk_b@smartcivic.com", "role": "worker", "is_available": True, "active_assignments": 0, "skills": ["road_repair"]})
        db.users.insert_one({"_id": self.officer_id, "name": "Officer B", "email": "off_b@smartcivic.com", "role": "officer"})
        db.issues.insert_one({"_id": self.issue_id, "category": "road", "type": "pothole", "severity": "medium", "status": "submitted", "location": {"type": "Point", "coordinates": [77.59, 12.97]}})

    def tearDown(self):
        db.users.delete_one({"_id": self.worker_id})
        db.users.delete_one({"_id": self.officer_id})
        db.issues.delete_one({"_id": self.issue_id})
        db.assignments.delete_many({"issue_id": str(self.issue_id)})

    def test_required_skills_mapping(self):
        issue = {"category": "road", "type": "pothole"}
        skills = get_required_worker_skills(issue)
        self.assertIn("road_repair", skills)

    def test_assign_worker_updates_db(self):
        assign_worker(str(self.issue_id), str(self.worker_id), str(self.officer_id))
        issue = db.issues.find_one({"_id": self.issue_id})
        self.assertEqual(str(issue["worker_id"]), str(self.worker_id))
        self.assertEqual(issue["status"], "assigned")

    def test_recommend_workers_includes_workers_without_skills(self):
        db.users.update_one({"_id": self.worker_id}, {"$set": {"skills": []}})

        recommendations = recommend_workers(db.issues.find_one({"_id": self.issue_id}), limit=100)

        self.assertIn(str(self.worker_id), [item["worker"]["id"] for item in recommendations])

    def test_assign_worker_closed_issue_does_not_mutate_assignment(self):
        db.issues.update_one({"_id": self.issue_id}, {"$set": {"status": "closed"}})

        with self.assertRaisesRegex(ValueError, "Illegal status transition from closed to assigned"):
            assign_worker(str(self.issue_id), str(self.worker_id), str(self.officer_id))

        issue = db.issues.find_one({"_id": self.issue_id})
        worker = db.users.find_one({"_id": self.worker_id})
        self.assertEqual(issue["status"], "closed")
        self.assertNotIn("worker_id", issue)
        self.assertEqual(worker["active_assignments"], 0)
        self.assertEqual(db.assignments.count_documents({"issue_id": str(self.issue_id)}), 0)

    def test_closed_issue_assignment_returns_bad_request(self):
        db.issues.update_one({"_id": self.issue_id}, {"$set": {"status": "closed"}})
        with self.app.app_context():
            token, _ = generate_tokens(str(self.officer_id), "officer", "Ward 1")

        response = self.app.test_client().post(
            f"/api/issues/{self.issue_id}/assign",
            json={"worker_id": str(self.worker_id)},
            headers={"Authorization": f"Bearer {token}"}
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"]["message"], "Illegal status transition from closed to assigned")
        self.assertEqual(db.users.find_one({"_id": self.worker_id})["active_assignments"], 0)
        self.assertEqual(db.assignments.count_documents({"issue_id": str(self.issue_id)}), 0)

if __name__ == "__main__":
    unittest.main()
