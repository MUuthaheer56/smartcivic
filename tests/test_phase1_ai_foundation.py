"""
Phase 1 — AI Foundation Layer Verification Tests
Validates the AI result envelope, model registry integrity guards, default-off feature flags,
and persistence to db.ai_decisions and db.ai_corrections.
"""
import os
import tempfile
import pytest
from bson import ObjectId
from app import create_app, db
from config import Config
from services.ai.envelope import make_ai_result
from services.ai.registry import load_model, registry
from services.ai.decision_logger import log_ai_decision, log_ai_correction

@pytest.fixture
def app_instance():
    app = create_app()
    app.config["TESTING"] = True
    return app

@pytest.fixture
def test_client(app_instance):
    return app_instance.test_client()

def test_feature_flags_default_off():
    """Confirms all Phase 1 feature flags default to False."""
    assert Config.AI_LOCAL_TEXT_ENABLED is False
    assert Config.AI_LOCAL_DETECTOR_ENABLED is False
    assert Config.AI_EMBED_DUPLICATES_ENABLED is False
    assert Config.AI_IMAGE_GATE_ENABLED is False
    assert Config.AI_REPAIR_V2_ENABLED is False
    assert Config.AI_ML_PRIORITY_SHADOW is False

def test_yolo_missing_model_never_raises():
    """Confirms yolo_service and registry fail closed without raising when model file is absent."""
    from services.yolo_service import run_yolo
    res = run_yolo("non_existent_test_image.jpg")
    assert isinstance(res, dict)
    assert res.get("available") is False

def test_envelope_structure():
    """Confirms envelope returns correct schema and types."""
    res = make_ai_result(
        value={"service": "road", "severity": "medium"},
        confidence=0.88,
        source="rules",
        model_version="v1.0",
        evidence_level="inferred",
        fallback_used=False
    )
    assert res["value"] == {"service": "road", "severity": "medium"}
    assert res["confidence"] == 0.88
    assert res["source"] == "rules"
    assert res["model_version"] == "v1.0"
    assert res["evidence_level"] == "inferred"
    assert res["fallback_used"] is False
    assert res["error"] is None

def test_registry_placeholder_and_missing_guards():
    """Validates that missing, empty, or 28-byte placeholder files return None cleanly."""
    # 1. Missing model
    missing_res = load_model("non_existent_model_xyz", custom_path="non_existent.onnx")
    assert missing_res is None

    # 2. 28-byte placeholder file
    with tempfile.NamedTemporaryFile(delete=False) as tf:
        tf.write(b"0" * 28)
        tf.flush()
        placeholder_path = tf.name

    try:
        placeholder_res = load_model("placeholder_test", custom_path=placeholder_path)
        assert placeholder_res is None, "Registry must refuse files <= 100 bytes"
    finally:
        if os.path.exists(placeholder_path):
            os.remove(placeholder_path)

def test_ai_decisions_and_corrections_logging(app_instance):
    """Verifies that decisions and corrections are stored in MongoDB."""
    with app_instance.app_context():
        test_issue_id = f"SC-TEST-AI-{ObjectId()}"

        # 1. Log AI decision
        env = make_ai_result(value={"test": True}, confidence=0.9, source="rules")
        log_ai_decision(db, test_issue_id, "text_analysis", env)

        saved_decision = db.ai_decisions.find_one({"issue_id": test_issue_id, "stage": "text_analysis"})
        assert saved_decision is not None, "ai_decisions row not inserted"
        assert saved_decision["envelope"]["confidence"] == 0.9
        assert "flag_snapshot" in saved_decision

        # 2. Log AI correction
        log_ai_correction(
            db,
            test_issue_id,
            field_changed="priority",
            before_value="P3",
            after_value="P1",
            actor_id="test_officer_id",
            actor_role="officer",
            reason="Emergency risk identified"
        )

        saved_correction = db.ai_corrections.find_one({"issue_id": test_issue_id, "field_changed": "priority"})
        assert saved_correction is not None, "ai_corrections row not inserted"
        assert saved_correction["before_value"] == "P3"
        assert saved_correction["after_value"] == "P1"

        # Cleanup
        db.ai_decisions.delete_many({"issue_id": test_issue_id})
        db.ai_corrections.delete_many({"issue_id": test_issue_id})
