import unittest

from services.evidence_priority import evaluate_priority


class TestEvidencePriority(unittest.TestCase):
    def test_same_source_is_counted_once_and_reporter_is_excluded(self):
        result = evaluate_priority({
            "severity": "high",
            "location_available": True,
            "image_available": True,
            "reporter_id": "reporter-1",
            "corroborating_sources": [
                {"source_id": "reporter-1"},
                {"source_id": "neighbor-1"},
                {"source_id": "neighbor-1"},
                {"source_id": "neighbor-2"},
            ],
        })

        self.assertEqual(result["score"], 48.0)
        self.assertEqual(
            [source["source_id"] for source in result["input_features"]["corroborating_sources"]],
            ["neighbor-1", "neighbor-2"],
        )

    def test_missing_image_is_recorded_without_lowering_score(self):
        complete = evaluate_priority({"severity": "medium", "location_available": True, "image_available": True})
        missing_image = evaluate_priority({"severity": "medium", "location_available": True, "image_available": False})

        self.assertEqual(complete["score"], missing_image["score"])
        self.assertEqual(missing_image["missing_evidence"], ["image"])
        self.assertFalse(missing_image["human_review_required"])

    def test_missing_location_is_recorded_and_requires_review(self):
        result = evaluate_priority({"severity": "low", "image_available": False})

        self.assertEqual(result["missing_evidence"], ["image", "location"])
        self.assertTrue(result["human_review_required"])


if __name__ == "__main__":
    unittest.main()