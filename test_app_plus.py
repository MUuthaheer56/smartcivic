"""
SmartCivic+ — Complete Verification & Automated Test Suite
"""
import unittest
from datetime import datetime, timedelta
from bson import ObjectId
from unittest.mock import MagicMock, patch

from services import ai_service, complaint_service, assignment_service, route_service, sla_service, priority_service, verification_service, audit_service
from routes.auth import generate_tokens, hash_password, check_password
from models.user import derive_citizen_tier
from utils import sanitize_description

class TestSmartCivicPlus(unittest.TestCase):
    
    def test_auth_password_hashing(self):
        pwd = "testpassword123"
        hashed = hash_password(pwd)
        self.assertNotEqual(pwd, hashed)
        self.assertTrue(check_password(pwd, hashed))
        self.assertFalse(check_password("wrongpassword", hashed))

    def test_derive_citizen_tier(self):
        self.assertEqual(derive_citizen_tier(10), "reporter")
        self.assertEqual(derive_citizen_tier(60), "verifier")
        self.assertEqual(derive_citizen_tier(200), "ward_guardian")

    def test_ai_text_analyzer_fallback(self):
        desc = "There is a massive pothole in the street causing accidents"
        res = ai_service.analyze_complaint_text(desc)
        self.assertEqual(res["category"], "road")
        self.assertEqual(res["type"], "pothole")
        self.assertEqual(res["severity"], "high")
        self.assertEqual(res["department"], "roads")
        self.assertEqual(res["provider"], "rule_based")

    def test_ai_image_analyzer_fallback(self):
        res = ai_service.analyze_complaint_image("pothole.jpg")
        self.assertEqual(res["severity"], "medium")
        self.assertEqual(res["provider"], "rule_based")
        self.assertIn("road_damage", res["image_detections"])

    def test_haversine_distance(self):
        # Distance between close points in Bangalore
        c1 = (12.9716, 77.5946)
        c2 = (12.9756, 77.5996)
        dist = route_service.haversine(c1, c2)
        self.assertTrue(dist > 0)
        self.assertTrue(dist < 1.0) # within 1km

    def test_priority_score_calculation(self):
        db_mock = MagicMock()
        db_mock.clusters.find_one.return_value = {"report_count": 3}
        
        issue = {
            "severity": "critical",
            "created_at": datetime.utcnow() - timedelta(hours=10),
            "cluster_id": ObjectId(),
            "description": "Near greenwood school",
            "sla_status": "urgent"
        }
        
        score = priority_service.calculate_priority(issue, db_mock)
        # Severity = 40, Age = 5, Duplicates = 6, Location = 10, SLA = 20 => 81
        self.assertAlmostEqual(score, 81.0, places=1)

    def test_sla_target_assignment(self):
        issue = {
            "severity": "high",
            "created_at": datetime.utcnow()
        }
        deadline = sla_service.assign_sla(issue)
        self.assertAlmostEqual((deadline - datetime.utcnow()).total_seconds() / 3600.0, 12.0, places=1)

    def test_sla_status_checks(self):
        db_mock = MagicMock()
        issue = {
            "_id": ObjectId(),
            "created_at": datetime.utcnow() - timedelta(hours=2),
            "sla_deadline": datetime.utcnow() - timedelta(minutes=10), # overdue
            "sla_status": "on_track",
            "citizen_id": ObjectId()
        }
        
        with patch('services.sla_service.send') as mock_send:
            status = sla_service.check_sla_status(issue)
            self.assertEqual(status, "breached")
            mock_send.assert_called()

    def test_worker_recommendations(self):
        db_mock = MagicMock()
        
        # Mock available workers
        db_mock.users.find.return_value = [
            {
                "_id": ObjectId("660000000000000000000001"),
                "name": "Worker A",
                "email": "workerA@smartcivic.com",
                "role": "worker",
                "skills": ["road_repair", "roads"],
                "current_location": {"type": "Point", "coordinates": [77.5956, 12.9726]},
                "active_assignments": 1,
                "is_available": True
            },
            {
                "_id": ObjectId("660000000000000000000002"),
                "name": "Worker B",
                "email": "workerB@smartcivic.com",
                "role": "worker",
                "skills": ["electrical"],
                "current_location": {"type": "Point", "coordinates": [77.5946, 12.9716]},
                "active_assignments": 0,
                "is_available": True
            }
        ]
        
        issue = {
            "category": "road",
            "location": {"type": "Point", "coordinates": [77.5946, 12.9716]},
            "sla_deadline": datetime.utcnow() + timedelta(hours=5)
        }
        
        # Patched db reference in recommendations
        with patch('services.assignment_service.db', db_mock):
            recs = assignment_service.recommend_workers(issue)
            self.assertEqual(len(recs), 1) # Only Worker A matches road skills
            self.assertEqual(recs[0]["worker"]["name"], "Worker A")

    def test_audit_logs(self):
        db_mock = MagicMock()
        db_mock.audit_logs.insert_one.return_value.inserted_id = ObjectId()
        
        with patch('services.audit_service.db', db_mock):
            log_id = audit_service.log_audit("issue", ObjectId(), ObjectId(), "STATUS_CHANGE", "status", "submitted", "assigned", "Worker dispatch.")
            self.assertIsNotNone(log_id)
            db_mock.audit_logs.insert_one.assert_called()

    def test_description_sanitizer(self):
        desc = "There is a massive pothole. Call 9876543210 or email test@smartcivic.com. <script>alert('XSS')</script> This is badword1."
        sanitized = sanitize_description(desc)
        self.assertNotIn("<script>", sanitized)
        self.assertNotIn("9876543210", sanitized)
        self.assertNotIn("test@smartcivic.com", sanitized)
        self.assertIn("[phone removed]", sanitized)
        self.assertIn("[email removed]", sanitized)
        self.assertIn("[removed]", sanitized)

    def test_indic_language_detection(self):
        # Kannada unicode text
        kannada_text = "ರಸ್ತೆಯಲ್ಲಿ ಗುಂಡಿ ಬಿದ್ದಿದೆ"
        res = ai_service.detect_and_translate(kannada_text)
        self.assertEqual(res["detected_language"], "kannada")
        
        # Hindi unicode text
        hindi_text = "सड़क पर गड्ढा है"
        res = ai_service.detect_and_translate(hindi_text)
        self.assertEqual(res["detected_language"], "hindi")

    def test_emergency_lifecycle(self):
        db_mock = MagicMock()
        issue_id = ObjectId()
        initial_issue = {
            "_id": issue_id,
            "status": "submitted",
            "priority_score": 10.0,
            "created_at": datetime.utcnow()
        }
        updated_issue = {
            "_id": issue_id,
            "status": "ai_reviewed",
            "priority_score": 100,
            "severity": "critical",
            "is_emergency": True,
            "created_at": initial_issue["created_at"]
        }
        db_mock.issues.find_one.return_value = updated_issue
        
        with patch('services.complaint_service.db', db_mock), patch('services.complaint_service.socketio'):
            updated = complaint_service.declare_emergency(issue_id, ObjectId(), "FLOODING")
            self.assertEqual(updated["priority_score"], 100)
            self.assertEqual(updated["severity"], "critical")
            self.assertEqual(updated["is_emergency"], True)

    def test_community_confirmations(self):
        db_mock = MagicMock()
        issue_id = ObjectId()
        initial_issue = {
            "_id": issue_id,
            "category": "road",
            "severity": "medium",
            "priority_score": 30.0,
            "status": "ai_reviewed",
            "community_confirmations": [],
            "confirmation_count": 0,
            "created_at": datetime.utcnow()
        }
        updated_issue = {
            "_id": issue_id,
            "category": "road",
            "severity": "medium",
            "priority_score": 31.5,
            "status": "ai_reviewed",
            "community_confirmations": [{"citizen_id": ObjectId()}],
            "confirmation_count": 1,
            "created_at": initial_issue["created_at"]
        }
        db_mock.issues.find_one.side_effect = [initial_issue, updated_issue]
        
        with patch('services.complaint_service.db', db_mock):
            updated = complaint_service.add_community_confirmation(issue_id, ObjectId(), "I saw it too")
            self.assertEqual(updated, 1)

    def test_search_query_parsing(self):
        # Local keyword heuristic fallback test
        parsed = ai_service.parse_search_query("show critical potholes in ward 5 older than 2 days")
        self.assertEqual(parsed.get("category"), "road")
        self.assertEqual(parsed.get("severity"), "critical")
        self.assertEqual(parsed.get("ward"), "Ward 5")
        self.assertEqual(parsed.get("min_age_hours"), 48)

    def test_ward_health_scoring(self):
        db_mock = MagicMock()
        # Mock database calls for health score checks
        db_mock.issues.count_documents.side_effect = [
            5, # unresolved > 24h
            2, # SLA breached
            1, # Recurring issues
            10, # Total issues
            6  # Resolved issues
        ]
        db_mock.issues.aggregate.return_value = [{"avg": 4.2}]
        
        with patch('services.briefing_service.db', db_mock):
            from services.briefing_service import calculate_ward_health_score
            score = calculate_ward_health_score("Ward 1")
            # Max score 100 - unresolved (5*1=5) - breached (2*3=6) - recurring (1*5=5) - rating (0) = 84
            self.assertEqual(score, 84)

    def test_predictive_hotspots_computation(self):
        db_mock = MagicMock()
        # Less than 100 closed complaints returns empty
        db_mock.issues.count_documents.return_value = 50
        with patch('services.prediction_service.db', db_mock):
            from services.prediction_service import compute_hotspots
            res = compute_hotspots()
            self.assertEqual(res, [])

    def test_ai_evaluation_recording(self):
        db_mock = MagicMock()
        from services.ai_evaluation_service import record_ai_evaluation
        with patch('services.ai_evaluation_service.db', db_mock):
            record_ai_evaluation(
                issue_id=ObjectId(),
                ai_task="classification",
                ai_prediction={"category": "road", "severity": "medium"},
                human_decision={"category": "water", "severity": "medium"},
                evaluated_by_id=ObjectId()
            )
            self.assertTrue(db_mock.ai_evaluations.insert_one.called)
            inserted_doc = db_mock.ai_evaluations.insert_one.call_args[0][0]
            self.assertEqual(inserted_doc["was_correct"], False)
            self.assertEqual(inserted_doc["correction_field"], "category")

    def test_infrastructure_health_score(self):
        db_mock = MagicMock()
        db_mock.infrastructure.find_one.return_value = {
            "segment_id": "RD-12",
            "segment_type": "road",
            "last_repair_at": None
        }
        db_mock.issues.find.return_value = [
            {"status": "submitted", "sla_status": "breached", "created_at": datetime.utcnow(), "is_recurring": False},
            {"status": "submitted", "sla_status": "on_track", "created_at": datetime.utcnow(), "is_recurring": False}
        ]
        from services.infrastructure_service import calculate_health_score
        with patch('services.infrastructure_service.db', db_mock):
            score = calculate_health_score("RD-12")
            # 100 - (1 unresolved < 7 days)*3 - (1 unresolved < 7 days)*3 - (1 SLA breach)*4 = 100 - 3 - 3 - 4 = 90
            self.assertEqual(score, 90)

    def test_simulation_calculations(self):
        db_mock = MagicMock()
        db_mock.issues.count_documents.return_value = 10
        db_mock.issues.aggregate.return_value = [{"avg_hours": 12.0}]
        db_mock.users.count_documents.return_value = 2
        from services.simulation_service import simulate_worker_addition
        with patch('services.simulation_service.db', db_mock):
            res = simulate_worker_addition("Ward 1", "roads", 2)
            self.assertEqual(res["current_workers"], 2)
            self.assertEqual(res["additional_workers"], 2)
            self.assertEqual(res["open_complaints"], 10)
            self.assertGreater(res["estimated_avg_resolution_hours"], 0)
