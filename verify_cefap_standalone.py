from services.cefap_pipeline import cefap_stage
from unittest.mock import MagicMock

mock_db = MagicMock()
mock_db.cefap_weights.find_one.return_value = None
mock_db.cefap_results.update_one.return_value = None

result = cefap_stage(mock_db, {
    "issue_id":          "test_001",
    "ward_id":           "ward_test",
    "service":           "roads",
    "text_severity":     "high",
    "text_confidence":   0.90,
    "image_severity":    None,
    "image_confidence":  None,
    "location_type":     "main_road",
    "vote_count":        3,
    "historical_complaints": [],
    "created_at":        __import__('datetime').datetime.utcnow(),
    "sla_deadline":      None,
})

assert 0.0 <= result["cips"] <= 1.0, "CIPS out of range"
assert result["priority"] in ("P0","P1","P2","P3"), "Invalid priority"
assert result["ctve_triggered"] == False, "CTVE should not fire — no image"
print("CEFAP integration test PASSED")
print(f"  CIPS:     {result['cips']}")
print(f"  Priority: {result['priority']}")
print(f"  E:        {result['evidence_reliability']}")
