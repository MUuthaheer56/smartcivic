import os
import json
import pytest
from unittest.mock import patch
from bson import ObjectId
from datetime import datetime

from app import create_app, db
from config import Config
from routes.auth import generate_tokens
from services.ai.registry import registry, load_model, MIN_MODEL_BYTES
from services.ai.priority_ml import predict_priority_ml
from services.complaint_service import create_complaint

@pytest.fixture
def app_instance():
    app = create_app()
    app.config["TESTING"] = True
    return app

@pytest.fixture
def test_client(app_instance):
    return app_instance.test_client()

def test_model_registry_priority_model():
    """Verify priority_model registration in ModelRegistry."""
    assert "priority_model" in registry._registry
    reg = registry._registry["priority_model"]
    assert "priority_model_v1.joblib" in reg["default_path"]

def test_priority_ml_placeholder_and_fallback(tmp_path):
    """Guards against placeholder (<100b) or missing files."""
    # 1. Missing file
    missing = str(tmp_path / "nonexistent.joblib")
    assert load_model("priority_model", custom_path=missing) is None

    # 2. Placeholder file
    ph = tmp_path / "tiny_ph.joblib"
    ph.write_bytes(b"dummy" * 5)
    assert load_model("priority_model", custom_path=str(ph)) is None

    # 3. Safe fallback in prediction
    res = predict_priority_ml({}, bundle_override=None)
    # If the bundle is loaded from default path, it works; if we force None, it degrades safely
    class EmptyBundleOverride:
        pass
    # passing empty bundle triggers safe fallback
    res_fallback = predict_priority_ml({}, bundle_override={"model": None})
    assert res_fallback["fallback_used"] is True
    assert res_fallback["error"] is not None
    assert res_fallback["value"]["suggested_priority"] is None
    assert res_fallback["value"]["advisory_only"] is True

def test_predict_priority_ml_envelope_and_critical():
    """Verifies AI envelope schema, probabilities, and critical priority detection."""
    critical_signals = {
        "text_severity": 1.0,
        "image_severity": 0.95,
        "location_impact": 1.0,
        "corroboration": 0.85,
        "recurrence": 0.3,
        "sla_risk": 1.0,
        "evidence_reliability": 0.9,
        "disagreement": 0.05,
        "monsoon_active": True
    }
    res = predict_priority_ml(critical_signals)
    assert "value" in res
    assert res["source"] == "ml_priority"
    assert res["evidence_level"] == "inferred"
    assert res["fallback_used"] is False
    assert "latency_ms" in res

    val = res["value"]
    assert val["suggested_priority"] in ["P0", "P1"]
    assert val["is_critical"] is True
    assert val["advisory_only"] is True
    assert "probabilities" in val
    assert sum(val["probabilities"].values()) > 0.95

def test_rule_r2_invariant_stored_priority_never_altered(app_instance, test_client):
    """
    Contract Rule R2: Priority = CEFAP.
    Verifies that enabling AI_ML_PRIORITY_SHADOW attaches advisory suggestion
    to issue view but NEVER modifies the canonical priority in db.issues.
    """
    with app_instance.app_context():
        # Create a low-priority complaint (P3)
        cid = str(ObjectId())
        issue_doc = create_complaint(
            citizen_id=cid,
            title="Minor roadside litter",
            description="Minor leaves and dry dust swept along residential curb",
            location={"ward": "Ward 1", "latitude": 12.9716, "longitude": 77.5946},
            category="sanitation",
            issue_type="litter"
        )
        assert issue_doc is not None
        issue_id = issue_doc["issue_id"]
        canonical_priority = issue_doc["priority"]

        # Ensure priority in DB
        db_issue_before = db.issues.find_one({"issue_id": issue_id})
        assert db_issue_before["priority"] == canonical_priority

        # Create mock officer user and token
        officer_id = str(ObjectId())
        officer_email = f"officer_{officer_id}@smartcivic.test"
        db.users.update_one(
            {"_id": ObjectId(officer_id)},
            {"$set": {"email": officer_email, "name": "Officer Test", "role": "officer", "ward": "all", "is_verified": True}},
            upsert=True
        )
        token, _ = generate_tokens(officer_id, "officer", "all")
        headers = {"Authorization": f"Bearer {token}"}

        with patch.object(Config, "AI_ML_PRIORITY_SHADOW", True):
            # Fetch issue details as officer
            resp = test_client.get(f"/api/issues/{issue_id}", headers=headers)
            assert resp.status_code == 200
            data = resp.get_json()

            # Advisory field must be present
            assert "ml_priority_suggestion" in data
            assert data["ml_priority_suggestion"]["advisory_only"] is True

            # Canonical priority in DB must be COMPLETELY UNCHANGED
            db_issue_after = db.issues.find_one({"issue_id": issue_id})
            assert db_issue_after["priority"] == canonical_priority
            assert data["priority"] == canonical_priority

def test_committed_evaluation_and_shap_reports():
    """Verify presence and validity of committed evaluation report and manifest."""
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    manifest_path = os.path.join(base_dir, "models_artifacts", "priority_model_manifest.json")
    report_path = os.path.join(base_dir, "ml", "reports", "priority_model_evaluation.json")

    assert os.path.exists(manifest_path), "Manifest missing"
    assert os.path.exists(report_path), "Evaluation report missing"

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    assert "sha256" in manifest
    assert manifest["critical_recall"] >= 0.90
    assert manifest["synthetic"] is True

    with open(report_path, "r", encoding="utf-8") as f:
        report = json.load(f)
    assert "models_comparison" in report
    assert "ML_Priority_RandomForest" in report["models_comparison"]
    assert "CEFAP_Adaptive_Fusion" in report["models_comparison"]
    assert "M1_Text_Only" in report["models_comparison"]
    assert "shap_feature_importance" in report
    assert len(report["shap_feature_importance"]) > 0
