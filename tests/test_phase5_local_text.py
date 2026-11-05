import pytest
import os
from unittest.mock import patch
from bson import ObjectId
from app import create_app, db
from config import Config
from services.ai.registry import registry, load_model, MIN_MODEL_BYTES
from services.ai.local_text import predict_local_text
from services.complaint_service import create_complaint

@pytest.fixture
def app_instance():
    app = create_app()
    app.config["TESTING"] = True
    return app

def test_model_registry_local_text():
    # Model should be registered in central registry
    assert "text_classifier" in registry._registry
    reg_info = registry._registry["text_classifier"]
    assert "models_artifacts" in reg_info["default_path"]

def test_local_text_placeholder_or_missing_rejection(tmp_path):
    # Test missing file fallback
    missing_path = str(tmp_path / "nonexistent.joblib")
    loaded = load_model("text_classifier", custom_path=missing_path)
    assert loaded is None

    # Test tiny placeholder rejection (<= 100 bytes)
    dummy_placeholder = tmp_path / "dummy_placeholder.joblib"
    dummy_placeholder.write_bytes(b"placeholder content")
    loaded_placeholder = load_model("text_classifier", custom_path=str(dummy_placeholder))
    assert loaded_placeholder is None

    # Test predict_local_text fallback when bundle is missing/empty
    res = predict_local_text("")
    assert res["fallback_used"] is True
    assert res["error"] is not None

def test_predict_local_text_envelope():
    res = predict_local_text("Huge dangerous pothole on main street")
    assert "value" in res
    assert "confidence" in res
    assert res["source"] == "local_text"
    assert res["evidence_level"] == "inferred"
    assert "model_version" in res
    assert "latency_ms" in res
    assert res["fallback_used"] is False

    val = res["value"]
    assert "service" in val
    assert "issue_type" in val
    assert "emergency" in val
    assert val["service"] == "roads"

def test_predict_local_text_emergency():
    res = predict_local_text("Electric pole sparking with live wire snapped and lying on wet street")
    assert res["value"]["emergency"] is True
    assert res["value"]["service"] == "electricity"

def test_rule_r8_emergency_cannot_be_lowered(app_instance):
    # Rule R8: Local model may raise emergency flag, but never lower it
    with app_instance.app_context():
        with patch.object(Config, "AI_LOCAL_TEXT_ENABLED", True):
            with patch("services.ai.local_text.predict_local_text") as mock_local:
                # Mock local model returning emergency=False
                mock_local.return_value = {
                    "value": {"service": "electricity", "issue_type": "live_wire", "emergency": False},
                    "confidence": 0.9,
                    "source": "local_text",
                    "model_version": "v1.0.0",
                    "evidence_level": "inferred",
                    "fallback_used": False,
                    "latency_ms": 10,
                    "error": None
                }
                cid = str(ObjectId())
                issue_doc = create_complaint(
                    citizen_id=cid,
                    title="Live wire snapped",
                    description="Live wire snapped and fallen on the road, urgent emergency",
                    location={"ward": 1, "latitude": 12.9716, "longitude": 77.5946},
                    category="electricity",
                    issue_type="live_wire"
                )
                assert issue_doc is not None
                # Priority must remain P0 because emergency regex flagged it
                assert issue_doc["priority"] == "P0"
                assert issue_doc["emergency"] is True

def test_rule_r8_local_model_can_raise_emergency(app_instance):
    # When rules did not flag emergency, local model can raise it
    with app_instance.app_context():
        with patch.object(Config, "AI_LOCAL_TEXT_ENABLED", True):
            with patch("services.ai.local_text.predict_local_text") as mock_local:
                mock_local.return_value = {
                    "value": {"service": "electricity", "issue_type": "transformer", "emergency": True},
                    "confidence": 0.95,
                    "source": "local_text",
                    "model_version": "v1.0.0",
                    "evidence_level": "inferred",
                    "fallback_used": False,
                    "latency_ms": 12,
                    "error": None
                }
                cid = str(ObjectId())
                issue_doc = create_complaint(
                    citizen_id=cid,
                    title="Transformer issue",
                    description="Transformer humming in back lane",
                    location={"ward": 1, "latitude": 12.9716, "longitude": 77.5946},
                    category="electricity",
                    issue_type="general"
                )
                assert issue_doc is not None
                assert issue_doc["emergency"] is True
                assert issue_doc["priority"] == "P0"

def test_shadow_mode_decision_logging(app_instance):
    # Under AI_LOCAL_TEXT_ENABLED, both text_analysis and local_text are logged to db.ai_decisions
    with app_instance.app_context():
        with patch.object(Config, "AI_LOCAL_TEXT_ENABLED", True):
            cid = str(ObjectId())
            issue_doc = create_complaint(
                citizen_id=cid,
                title="Pothole near junction",
                description="Deep pothole near junction causing vehicle breakdown",
                location={"ward": 2, "latitude": 12.9716, "longitude": 77.5946},
                category="roads",
                issue_type="pothole"
            )
            assert issue_doc is not None
            issue_id = issue_doc["issue_id"]

            decisions = list(db.ai_decisions.find({"issue_id": issue_id}))
            stages = [d.get("stage") for d in decisions]
            assert "text_analysis" in stages
            assert "local_text" in stages
