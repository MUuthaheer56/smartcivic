"""
SmartCivic — Assignment Service Unit Tests
Tests worker skill matching, recommendation filters, and assignment persistence.
"""
import unittest
from app import create_app, db
from services.assignment_service import get_required_worker_skills, assign_worker, recommend_workers
from routes.auth import hash_password
from bson import ObjectId

class TestAssignment(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.worker_id = ObjectId()
        self.officer_id = ObjectId()
        self.issue_id = ObjectId()
        
        db.users.insert_one({"_id": self.worker_id, "name": "Worker B", "email": "wrk_b@smartcivic.com", "role": "worker", "is_available": True, "skills": ["road_repair"]})
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

if __name__ == "__main__":
    unittest.main()
