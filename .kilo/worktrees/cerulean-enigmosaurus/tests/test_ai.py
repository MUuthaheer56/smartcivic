"""
SmartCivic — AI Service Unit Tests
Tests text classification, image availability handling, and fusion weighting guarantees.
"""
import unittest
from services import ai_service

class TestAI(unittest.TestCase):
    def test_analyze_text_confidence_type(self):
        res = ai_service.analyze_text("Large pothole causing severe traffic backup")
        self.assertIn("confidence_type", res)
        self.assertIn(res["confidence_type"], ["model", "model_reported", "heuristic"])

    def test_analyze_image_missing_model_unavailable(self):
        res = ai_service.analyze_image("non_existent_image.jpg")
        self.assertFalse(res["available"])
        self.assertIn("reason", res)

    def test_fuse_predictions_unavailable_image_text_only(self):
        text_res = ai_service.analyze_text("Water pipe burst near residential main street")
        img_res = {"available": False, "reason": "model_unavailable"}
        fusion = ai_service.fuse_predictions(text_res, img_res)
        
        self.assertEqual(fusion["fusion_method"], "text_only")
        self.assertNotEqual(fusion.get("confidence_type"), "model")

if __name__ == "__main__":
    unittest.main()
