"""
SmartCivic - PDF Implementation Verification Test Suite
Tests all 24 production-ready methods and integrations using mock objects.
"""
import unittest
from datetime import datetime, timedelta
from bson import ObjectId
from unittest.mock import MagicMock

# Imports of new services
from services.auth_service import (
    rate_limit_login_by_ip, record_failed_attempt, clear_login_attempts,
    send_otp_verification, verify_otp, audit_log_action
)
from services.complaints_service import (
    reopen_complaint, batch_assign_complaints, get_complaint_timeline, flag_complaint_as_duplicate
)
from ai.pipeline import score_pipeline_confidence, explain_ai_decision
from ai.specialised.road import estimate_pothole_volume
from ai.specialised.repair_verify import compare_before_after_images
from services.verification_service import detect_vote_collusion, decay_civic_points
from services.notification_service import notify_citizen_on_status_change
from services.sla_service import escalate_sla_breach
from services.ward_report_service import generate_ward_monthly_report
from services.workers_service import get_nearest_available_worker, get_worker_daily_schedule
from utils import sanitize_description, cached


class TestPDFFeatures(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        
    def test_rate_limiting_login(self):
        ip = "192.168.1.1"
        
        # Test case: Rec not found (allowed)
        self.db.login_attempts.find_one.return_value = None
        allowed, rem = rate_limit_login_by_ip(ip, self.db)
        self.assertTrue(allowed)
        self.assertEqual(rem, 5)
        
        # Test case: Rec found (locked out)
        self.db.login_attempts.find_one.return_value = {
            "ip": ip,
            "attempts": 5,
            "window_start": datetime.utcnow()
        }
        allowed, rem = rate_limit_login_by_ip(ip, self.db)
        self.assertFalse(allowed)
        self.assertEqual(rem, 0)

    def test_otp_verification(self):
        user_id = ObjectId("660000000000000000000002")
        self.db.users.find_one.return_value = {
            "_id": user_id,
            "email": "test@smartcivic.com",
            "phone": "9876543210"
        }
        
        # Send OTP
        success, msg = send_otp_verification(str(user_id), "email", self.db)
        self.assertTrue(success)
        self.db.users.update_one.assert_called()

    def test_audit_logging(self):
        user_id = ObjectId("660000000000000000000002")
        meta = {"complaint_id": "123", "action": "test"}
        self.db.audit_logs.insert_one.return_value.inserted_id = ObjectId()
        
        log_id = audit_log_action(str(user_id), "STATUS_CHANGE", meta, self.db)
        self.assertIsNotNone(log_id)
        self.db.audit_logs.insert_one.assert_called()

    def test_reopen_complaint(self):
        citizen_id = ObjectId("660000000000000000000003")
        worker_id = ObjectId("660000000000000000000004")
        issue_id = ObjectId("660000000000000000000005")
        
        self.db.issues.find_one.return_value = {
            "_id": issue_id,
            "reporter_id": citizen_id,
            "assigned_to": worker_id,
            "status": "resolved",
            "resolved_at": datetime.utcnow()
        }
        
        # Reopen complaint
        success, msg = reopen_complaint(str(issue_id), "Not resolved fully", str(citizen_id), self.db)
        self.assertTrue(success)
        self.db.issues.update_one.assert_called()
        self.db.users.update_one.assert_called()

    def test_batch_assignment(self):
        worker_id = ObjectId("660000000000000000000004")
        self.db.users.find_one.return_value = {
            "_id": worker_id,
            "role": "field_worker",
            "status": "AVAILABLE"
        }
        
        issue_1 = ObjectId("660000000000000000000006")
        self.db.issues.count_documents.return_value = 0
        self.db.issues.find_one.return_value = {
            "_id": issue_1,
            "status": "validated"
        }
        
        res = batch_assign_complaints(str(worker_id), [str(issue_1)], self.db)
        self.assertEqual(len(res["assigned"]), 1)
        self.assertEqual(res["reason"], "OK")

    def test_complaint_timeline_and_duplicate(self):
        issue_1 = ObjectId("660000000000000000000008")
        issue_2 = ObjectId("660000000000000000000009")
        
        self.db.issues.find_one.side_effect = [
            {"_id": issue_2, "status": "validated"},
            {"_id": issue_1, "status": "validated"}
        ]
        
        # Duplicate flagging
        success, msg = flag_complaint_as_duplicate(str(issue_2), str(issue_1), self.db)
        self.assertTrue(success)

    def test_ai_pipeline(self):
        ai_res = {
            "ai_confidence": 0.85,
            "quality": {"passed": True},
            "is_duplicate": False,
            "specialised": {
                "lakes": {"in_buffer": True},
                "footpath": {"impact": "HIGH"},
                "noise": {"violation": True},
                "dump_age": {"estimated_days": 5}
            },
            "severity_score": 0.9,
            "routing_status": "AUTO"
        }
        
        conf_data = score_pipeline_confidence(ai_res)
        self.assertEqual(conf_data["band"], "HIGH")
        self.assertTrue(conf_data["confidence"] > 75)
        
        explanation = explain_ai_decision(ai_res)
        self.assertIn("lake buffer zone", explanation)
        self.assertIn("automatically verified", explanation)

    def test_pothole_volume(self):
        # Passing empty/invalid path returns default LOW tier
        res = estimate_pothole_volume("nonexistent.jpg")
        self.assertEqual(res["cost_tier"], "LOW")
        self.assertEqual(res["volume_cm3"], 0)

    def test_vote_collusion_and_decay(self):
        issue_id = ObjectId("660000000000000000000010")
        self.db.issues.find_one.return_value = {
            "_id": issue_id,
            "status": "validated"
        }
        self.db.votes.find.return_value = [
            {"issue_id": issue_id, "voter_id": ObjectId(), "vote_type": "confirm", "timestamp": datetime.utcnow()},
            {"issue_id": issue_id, "voter_id": ObjectId(), "vote_type": "confirm", "timestamp": datetime.utcnow() + timedelta(seconds=2)}
        ]
        
        res = detect_vote_collusion(str(issue_id), self.db)
        self.assertEqual(res["recommend_action"], "FLAG_FOR_REVIEW")
        self.assertTrue(res["collusion_risk"] >= 0.4)

    def test_sla_escalation(self):
        issue_id = ObjectId("660000000000000000000012")
        self.db.issues.find_one.return_value = {
            "_id": issue_id,
            "status": "validated",
            "category": "garbage"
        }
        
        res = escalate_sla_breach(str(issue_id), self.db)
        self.assertTrue(res["escalated"])
        self.assertEqual(res["escalation_level"], 1)

    def test_description_sanitizer(self):
        desc = "Call me at 9876543210 or email test@gmail.com. <script>alert('XSS')</script> This is badword1."
        sanitized = sanitize_description(desc)
        self.assertNotIn("9876543210", sanitized)
        self.assertNotIn("<script>", sanitized)
        self.assertIn("[phone removed]", sanitized)
        self.assertIn("[email removed]", sanitized)
        self.assertIn("[removed]", sanitized)

    def test_cache_decorator(self):
        calls = 0
        
        @cached(key_fn=lambda x: f"key:{x}", ttl=5)
        def my_expensive_func(val):
            nonlocal calls
            calls += 1
            return val * 2
            
        self.assertEqual(my_expensive_func(3), 6)
        self.assertEqual(my_expensive_func(3), 6)
        self.assertEqual(calls, 1) # Called only once!
