import unittest
import base64
import json
import sys
import os
from bson import ObjectId
from datetime import datetime, timedelta

# Ensure root folder is in sys.path
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from app import create_app
from ai.detector import detect_road_damage
from ai.quality import check_image_quality
from ai.severity import estimate_severity
from ai.confidence import route_confidence_threshold
from ai.duplicate import check_geospatial_duplicate, check_visual_duplicate, calculate_cosine_similarity
from ai.repair import verify_repair_performance
from ai.nlp import classify_complaint_text
from ai.analytics import get_severity_heatmap, calculate_civic_risk_scores, get_worker_performance_stats

class TestSmartCivicAIUpgrade(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        # Create a Flask test application context
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.client = cls.app.test_client()
        cls.ctx = cls.app.app_context()
        cls.ctx.push()
        
    @classmethod
    def tearDownClass(cls):
        cls.ctx.pop()
        
    def setUp(self):
        # Clear test databases collections where needed
        import app
        app.db.issues.delete_many({"is_test": True})
        app.db.repair_verification.delete_many({})
        
    def tearDown(self):
        import app
        app.db.issues.delete_many({"is_test": True})
        app.db.repair_verification.delete_many({})

    def get_dummy_image_bytes(self):
        # Return valid transparent 1x1 PNG bytes
        return base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
        )

    def test_algorithm_1_detector(self):
        img_bytes = self.get_dummy_image_bytes()
        res = detect_road_damage(img_bytes)
        self.assertIn("detected_class", res)
        self.assertIn("confidence", res)
        self.assertIn("bounding_box", res)
        self.assertIn("visual_severity", res)
        self.assertIn("severity_level", res)
        
    def test_algorithm_2_image_quality(self):
        img_bytes = self.get_dummy_image_bytes()
        res = check_image_quality(img_bytes)
        self.assertIn("quality_score", res)
        self.assertIn("acceptable", res)
        self.assertIn("issues", res)
        
    def test_algorithm_3_severity_estimation(self):
        res = estimate_severity(confidence=0.90, bbox_area=400, image_area=1600, category="pothole")
        self.assertEqual(res["severity_level"], "LOW") # 0.90 * 0.25 * 1.5 * 10 = 3.375 -> rounded is 3.4 or similar, wait. Let's see: 0.9 * 0.25 * 1 * 1.5 * 10 = 3.375
        self.assertGreaterEqual(res["severity_score"], 1.0)
        
    def test_algorithm_4_confidence_routing(self):
        res_auto = route_confidence_threshold(0.88)
        self.assertEqual(res_auto["routing"], "AUTO")
        
        res_verify = route_confidence_threshold(0.72)
        self.assertEqual(res_verify["routing"], "COMMUNITY_VERIFY")
        
        res_review = route_confidence_threshold(0.45)
        self.assertEqual(res_review["routing"], "ADMIN_REVIEW")

    def test_algorithm_5_nlp_tagging(self):
        res_road = classify_complaint_text("huge pothole on the asphalt lane")
        self.assertEqual(res_road["category"], "road damage")
        self.assertEqual(res_road["subcategory"], "pothole")
        
        res_garbage = classify_complaint_text("overflowing trash bin smelling bad")
        self.assertEqual(res_garbage["category"], "waste management")

    def test_algorithm_6_geospatial_duplicate(self):
        # Insert a mock issue
        comm_id = ObjectId()
        import app
        issue_id = app.db.issues.insert_one({
            "is_test": True,
            "community_id": comm_id,
            "category": "road damage",
            "lat": 12.9716,
            "lng": 77.5946,
            "status": "validated",
            "title": "Mock Pothole"
        }).inserted_id
        
        matches = check_geospatial_duplicate(12.9718, 77.5948, "road damage", str(comm_id))
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["complaint_id"], str(issue_id))

    def test_algorithm_7_cosine_similarity(self):
        vec_a = [1.0, 0.0, 0.0]
        vec_b = [1.0, 0.0, 0.0]
        sim = calculate_cosine_similarity(vec_a, vec_b)
        self.assertAlmostEqual(sim, 1.0)
        
        vec_c = [0.0, 1.0, 0.0]
        sim_orth = calculate_cosine_similarity(vec_a, vec_c)
        self.assertAlmostEqual(sim_orth, 0.0)

    def test_algorithm_8_repair_verification(self):
        comm_id = ObjectId()
        import app
        issue_id = app.db.issues.insert_one({
            "is_test": True,
            "community_id": comm_id,
            "category": "road damage",
            "lat": 12.9716,
            "lng": 77.5946,
            "status": "assigned",
            "title": "Road Repair Check",
            "ai_confidence": 0.95
        }).inserted_id
        
        # Effective repair (before=0.95, after=0.12) -> Drop is 0.83 (>=50 points), after is 0.12 (<30%)
        res_effective = verify_repair_performance(str(issue_id), 0.95, 0.12)
        self.assertEqual(res_effective["result"], "VERIFIED")
        
        # Ineffective repair (before=0.95, after=0.79)
        res_failed = verify_repair_performance(str(issue_id), 0.95, 0.79)
        self.assertEqual(res_failed["result"], "FAILED")

    def test_algorithm_9_heatmap(self):
        comm_id = ObjectId()
        import app
        app.db.issues.insert_one({
            "is_test": True,
            "community_id": comm_id,
            "category": "road damage",
            "lat": 12.9716,
            "lng": 77.5946,
            "status": "validated",
            "severity": 8.0
        })
        
        heatmap = get_severity_heatmap(category="road damage", status="validated")
        self.assertGreaterEqual(len(heatmap), 1)

    def test_algorithm_10_risk_scores(self):
        import app
        app.db.issues.insert_one({
            "is_test": True,
            "community_id": ObjectId(),
            "category": "road damage",
            "lat": 12.9716,
            "lng": 77.5946,
            "status": "validated",
            "severity": 8.0,
            "created_at": datetime.utcnow()
        })
        
        risk_list = calculate_civic_risk_scores()
        self.assertGreaterEqual(len(risk_list), 1)
        self.assertIn("risk_score", risk_list[0])

    def test_algorithm_11_worker_performance(self):
        worker_id = ObjectId()
        import app
        app.db.issues.insert_one({
            "is_test": True,
            "community_id": ObjectId(),
            "assigned_to": worker_id,
            "status": "resolved",
            "severity": 5,
            "assigned_at": datetime.utcnow() - timedelta(days=2),
            "resolved_at": datetime.utcnow(),
            "sla_deadline": datetime.utcnow() + timedelta(days=1)
        })
        
        stats = get_worker_performance_stats(str(worker_id))
        self.assertEqual(stats["assigned"], 1)
        self.assertEqual(stats["completed"], 1)
        self.assertGreaterEqual(stats["performance_score"], 10)

    def test_api_endpoints_ai(self):
        # 1. Analyze Image
        response = self.client.post('/api/ai/analyze-image', json={
            "image": base64.b64encode(self.get_dummy_image_bytes()).decode('utf-8')
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("detected_class", response.json)
        
        # 2. Check Quality
        response = self.client.post('/api/ai/check-image-quality', json={
            "image": base64.b64encode(self.get_dummy_image_bytes()).decode('utf-8')
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("quality_score", response.json)
        
        # 3. Classify complaint description
        response = self.client.post('/api/ai/classify-complaint', json={
            "description": "sewage is overflowing and stinking"
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["category"], "sewage")

        # 4. Check Duplicate
        response = self.client.post('/api/ai/check-duplicate', json={
            "lat": 12.9716,
            "lng": 77.5946,
            "category": "road damage",
            "community_id": str(ObjectId())
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("is_duplicate", response.json)

    def test_api_endpoints_analytics(self):
        response = self.client.get('/api/analytics/heatmap')
        self.assertEqual(response.status_code, 200)
        
        response = self.client.get('/api/analytics/risk')
        self.assertEqual(response.status_code, 200)
        
        response = self.client.get(f'/api/analytics/worker-performance?worker_id={ObjectId()}')
        self.assertEqual(response.status_code, 200)

if __name__ == "__main__":
    unittest.main()
