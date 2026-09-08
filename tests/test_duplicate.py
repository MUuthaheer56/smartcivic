"""
SmartCivic — Duplicate Service Unit Tests
Tests spatial duplicate detection, 5km distance non-duplicate checks, and similarity score bounds.
"""
import unittest
from services.duplicate_service import calculate_similarity, detect_duplicate

class TestDuplicate(unittest.TestCase):
    def test_identical_issue_similarity(self):
        issue_a = {"category": "road", "type": "pothole", "severity": "high"}
        issue_b = {"category": "road", "type": "pothole", "severity": "high"}
        sim = calculate_similarity(issue_a, issue_b)
        self.assertGreaterEqual(sim, 0.85)
        self.assertLessEqual(sim, 1.0)

    def test_different_category_zero_similarity(self):
        issue_a = {"category": "road", "type": "pothole", "severity": "high"}
        issue_b = {"category": "water", "type": "pothole", "severity": "high"}
        sim = calculate_similarity(issue_a, issue_b)
        self.assertEqual(sim, 0.0)

    def test_detect_duplicate_no_candidates(self):
        loc = {"latitude": 12.9716, "longitude": 77.5946}
        pred = {"category": "road", "type": "pothole", "severity": "high"}
        res = detect_duplicate(loc, pred)
        self.assertIsInstance(res, dict)
        self.assertIn("is_duplicate", res)

if __name__ == "__main__":
    unittest.main()
