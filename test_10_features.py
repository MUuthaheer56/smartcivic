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
from ai.drain.drain_predictor import compute_drain_risk, run_drain_prediction
from ai.streetlight.darkness_detector import check_streetlight_outage, is_night_photo
from ai.footpath.encroachment_detector import compute_footpath_impact, estimate_encroachment
from ai.dump.dump_age_estimator import extract_aging_features, estimate_dump_age, check_repeat_location
from ai.lakes.lake_boundary_checker import check_lake_buffer
from ai.animals.animal_detector import detect_animals
from ai.animals.hotspot_clusterer import compute_animal_hotspots
from ai.construction.safety_detector import detect_construction_hazard
from ai.construction.permit_checker import check_construction_permit
from ai.coordination.coordination_analyzer import compute_coordination_failures
from ai.trust.civic_trust_scorer import compute_ward_trust_scores

class TestSmartCivic10Features(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.client = cls.app.test_client()
        cls.ctx = cls.app.app_context()
        cls.ctx.push()
        
    @classmethod
    def tearDownClass(cls):
        cls.ctx.pop()
        
    def setUp(self):
        import app
        app.db.issues.delete_many({"is_test": True})
        app.db.drain_risk.delete_many({})
        app.db.construction_permits.delete_many({})
        app.db.coordination_failures.delete_many({})
        app.db.ward_trust_scores.delete_many({})
        app.db.animal_hotspots.delete_many({})
        app.db.noise_readings.delete_many({})
        
    def tearDown(self):
        import app
        app.db.issues.delete_many({"is_test": True})
        app.db.drain_risk.delete_many({})
        app.db.construction_permits.delete_many({})
        app.db.coordination_failures.delete_many({})
        app.db.ward_trust_scores.delete_many({})
        app.db.animal_hotspots.delete_many({})
        app.db.noise_readings.delete_many({})

    def test_feature_1_drain_predictor(self):
        import app
        # Insert mock garbage issues near a known drain (Sarjapur D-042: 12.9018, 77.6741)
        app.db.issues.insert_one({
            "is_test": True,
            "category": "garbage",
            "status": "pending_validation",
            "lat": 12.9019,
            "lng": 77.6742,
            "severity": 8,
            "created_at": datetime.utcnow()
        })
        
        drains_predicted = run_drain_prediction(app.db)
        self.assertGreaterEqual(len(drains_predicted), 0)
        
        # Check if record was written to drain_risk collection
        risk_record = app.db.drain_risk.find_one({"drain_id": "D-042"})
        self.assertIsNotNone(risk_record)
        self.assertGreater(risk_record["risk_score"], 0)

    def test_feature_2_streetlight_passive(self):
        import app
        # Nighttime photo timestamp
        night_time = datetime(2026, 8, 25, 23, 0, 0)
        self.assertTrue(is_night_photo(night_time))
        
        res = check_streetlight_outage("dummy_path.jpg", 12.9716, 77.5946, night_time, app.db)
        self.assertIsNotNone(res)
        self.assertEqual(res["detection_type"], "streetlight_outage")

    def test_feature_3_footpath_encroachment(self):
        yolo_detections = [{
            "class": "motorcycle",
            "bbox": [150.0, 400.0, 300.0, 600.0],
            "confidence": 0.95
        }]
        # Footpath area in 640x640: (576 - 64) * (640 - 384) = 512 * 256 = 131,072
        # Blocked area in footpath: x overlaps max(150, 64) to min(300, 576) -> 150 to 300 = 150 width
        # y overlaps max(400, 384) to min(600, 640) -> 400 to 600 = 200 height. Blocked = 30,000
        # Encroachment pct = (30000 / 131072) * 100 = 22.9%
        enc_pct = estimate_encroachment(yolo_detections, 640, 640)
        self.assertEqual(enc_pct, 22.9)
        
        res = compute_footpath_impact(yolo_detections, 640, 640, 12.9716, 77.5946)
        self.assertEqual(res["impact_level"], "LOW")
        self.assertTrue(res["near_sensitive_poi"]) # Because 12.9716 trigger mock school POI

    def test_feature_4_dump_age_timeline(self):
        import app
        features = {
            "saturation": 40.0,
            "texture_sharpness": 150.0,
            "green_ratio": 1.15,
            "brightness": 50.0
        }
        res = estimate_dump_age(features)
        self.assertEqual(res["estimated_age_range"], "14+ days")
        self.assertTrue(res["neglect_indicator"])
        
        # Test repeat check
        app.db.issues.insert_one({
            "is_test": True,
            "category": "garbage",
            "status": "resolved",
            "lat": 12.9716,
            "lng": 77.5946,
            "created_at": datetime.utcnow()
        })
        self.assertTrue(check_repeat_location(app.db, 12.9716, 77.5946))

    def test_feature_6_lake_encroachment(self):
        # Koramangala Lake: Polygon [77.6240, 12.9350] to [77.6250, 12.9360]
        # Point inside lake
        res_inside = check_lake_buffer(12.9355, 77.6245)
        self.assertTrue(res_inside["violation"])
        self.assertEqual(res_inside["water_body"], "Koramangala Lake")
        self.assertEqual(res_inside["escalation"], "REVENUE_DEPARTMENT")

    def test_feature_7_stray_animal_hotspots(self):
        import app
        # Create 5 animal reports in the same location to form a hotspot
        for _ in range(5):
            app.db.issues.insert_one({
                "is_test": True,
                "category": "stray animal",
                "lat": 12.9716,
                "lng": 77.5946,
                "animal_type": "dog",
                "created_at": datetime.utcnow()
            })
            
        hotspots = compute_animal_hotspots(app.db)
        self.assertEqual(len(hotspots), 1)
        self.assertEqual(hotspots[0]["report_count"], 5)
        self.assertEqual(hotspots[0]["hotspot_score"], 50)

    def test_feature_8_construction_safety(self):
        import app
        hazard = detect_construction_hazard("dummy.jpg")
        self.assertTrue(hazard["hazard_detected"])
        
        # No permit
        permit_none = check_construction_permit(12.9716, 77.5946, app.db)
        self.assertFalse(permit_none["permit_found"])
        
        # Active permit
        app.db.construction_permits.insert_one({
            "lat": 12.9716,
            "lng": 77.5946,
            "permit_id": "P-456",
            "contractor_name": "L&T",
            "valid_until": "2026-12-31",
            "status": "ACTIVE"
        })
        permit_active = check_construction_permit(12.9716, 77.5946, app.db)
        self.assertTrue(permit_active["permit_found"])
        self.assertEqual(permit_active["contractor"], "L&T")

    def test_feature_9_coordination_failure(self):
        import app
        # Create 2 road excavation reports on the same segment (R-12.9716-77.5946) within 90 days
        app.db.issues.insert_one({
            "is_test": True,
            "category": "road damage",
            "lat": 12.9716,
            "lng": 77.5946,
            "status": "resolved",
            "department": "BWSSB",
            "created_at": datetime.utcnow() - timedelta(days=10)
        })
        app.db.issues.insert_one({
            "is_test": True,
            "category": "road excavation",
            "lat": 12.9716,
            "lng": 77.5946,
            "status": "resolved",
            "department": "BESCOM",
            "created_at": datetime.utcnow()
        })
        
        failures = compute_coordination_failures(app.db)
        self.assertGreaterEqual(len(failures), 1)
        self.assertEqual(failures[0]["repeat_count"], 2)

    def test_feature_10_civic_trust_scorer(self):
        import app
        # Insert a community and issues to compute ward trust
        comm_id = ObjectId()
        app.db.issues.insert_one({
            "is_test": True,
            "community_id": comm_id,
            "category": "road damage",
            "lat": 12.9716,
            "lng": 77.5946,
            "status": "resolved",
            "created_at": datetime.utcnow() - timedelta(days=5),
            "validated_at": datetime.utcnow() - timedelta(days=4.5),
            "repair_verified": True
        })
        
        scores = compute_ward_trust_scores(app.db)
        self.assertGreaterEqual(len(scores), 1)
        wards_in_scores = [s["ward"] for s in scores]
        self.assertIn(str(comm_id), wards_in_scores)
        
        # Find score for our community
        our_score = next(s for s in scores if s["ward"] == str(comm_id))
        self.assertGreater(our_score["trust_score"], 0)

    def test_new_api_endpoints_ai(self):
        # 1. Footpath
        response = self.client.post('/api/ai/analyze-footpath', json={
            "image": base64.b64encode(b"dummy_bytes").decode('utf-8')
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("encroachment_pct", response.json)
        
        # 2. Dump age
        response = self.client.post('/api/ai/estimate-dump-age', json={
            "image": base64.b64encode(b"dummy_bytes").decode('utf-8')
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("estimated_age_range", response.json)
        
        # 3. Lake boundary
        response = self.client.post('/api/ai/check-lake-boundary', json={
            "lat": 12.9355,
            "lng": 77.6245
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["violation"])
        
        # 4. Construction safety
        response = self.client.post('/api/ai/check-construction-safety', json={
            "image": base64.b64encode(b"dummy_bytes").decode('utf-8')
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("hazard_detected", response.json)
        
        # 5. Drain risk
        response = self.client.get('/api/ai/drain-risk')
        self.assertEqual(response.status_code, 200)

    def test_new_api_endpoints_complaints_and_analytics(self):
        import app
        issue_id = app.db.issues.insert_one({
            "is_test": True,
            "category": "noise",
            "lat": 12.9716,
            "lng": 77.5946,
            "status": "pending_validation"
        }).inserted_id
        
        # 1. Submit noise reading
        response = self.client.post('/api/complaints/noise-reading', json={
            "complaint_id": str(issue_id),
            "measured_db": 68,
            "legal_limit_db": 55,
            "zone": "residential",
            "is_violation": True,
            "excess_db": 13
        })
        self.assertEqual(response.status_code, 200)
        
        # Check if tags were updated
        updated = app.db.issues.find_one({"_id": issue_id})
        self.assertTrue(updated["noise_validated"])
        self.assertIn("legally_validated_noise_violation", updated["tags"])
        
        # 2. Get coordination failures
        response = self.client.get('/api/analytics/coordination-failures')
        self.assertEqual(response.status_code, 200)
        
        # 3. Get ward trust
        response = self.client.get('/api/analytics/ward-trust')
        self.assertEqual(response.status_code, 200)

if __name__ == "__main__":
    unittest.main()
