"""
SmartCivic - Phase 4 Tests: Road Damage Detector & Severity Rubric
Tests ONNX model loading via registry, placeholder detection (<100b),
CPU inference, written severity rubric, CEFAP image_source signal,
and committed evaluation report.
"""
import os
import json
import pytest
import numpy as np
from PIL import Image

from config import Config
from services.ai.registry import registry, load_model, MIN_MODEL_BYTES
from services.ai.road_detector import run_road_detector, _preprocess_image
from services.ai.severity_rubric import calculate_defect_severity, DEFECT_CLASSES
from services.cefap_pipeline import cefap_stage, _img


def test_severity_rubric_calculations():
    """Verify provisional severity rubric tiers and score bounds."""
    # Pothole (D40)
    sev_crit, score_crit = calculate_defect_severity("D40", area_ratio=0.15)
    assert sev_crit == "critical"
    assert score_crit >= 0.90

    sev_high, score_high = calculate_defect_severity("D40", area_ratio=0.05)
    assert sev_high == "high"
    assert 0.70 <= score_high < 0.90

    sev_med, score_med = calculate_defect_severity("D40", area_ratio=0.01)
    assert sev_med == "medium"
    assert score_med == 0.50

    # Alligator Crack (D20)
    sev_d20, _ = calculate_defect_severity("D20", area_ratio=0.08)
    assert sev_d20 == "medium"

    # Longitudinal Crack (D00)
    sev_d00, _ = calculate_defect_severity("D00", area_ratio=0.05)
    assert sev_d00 == "low"

    # Unknown defect fallback
    sev_unk, score_unk = calculate_defect_severity("UNKNOWN_CODE", 0.1)
    assert sev_unk == "medium"
    assert score_unk == 0.40


def test_registry_placeholder_and_missing_guards(tmp_path):
    """
    Exit Gate: Model registry safely rejects files <= 100 bytes (placeholders)
    and missing paths without crashing.
    """
    # 1. Non-existent file
    assert load_model("road_detector", custom_path=str(tmp_path / "nonexistent.onnx")) is None

    # 2. 28-byte placeholder file
    placeholder_file = tmp_path / "placeholder.onnx"
    placeholder_file.write_bytes(b"ONNX_PLACEHOLDER_28_BYTES!!!")
    assert os.path.getsize(placeholder_file) == 28
    assert os.path.getsize(placeholder_file) <= MIN_MODEL_BYTES
    assert load_model("road_detector", custom_path=str(placeholder_file)) is None

    # 3. 0-byte empty file
    empty_file = tmp_path / "empty.onnx"
    empty_file.write_bytes(b"")
    assert load_model("road_detector", custom_path=str(empty_file)) is None


def test_road_detector_clean_fallback_when_unavailable(tmp_path):
    """
    When model is missing or placeholder, run_road_detector must return a standard envelope
    with available=False and fallback_used=True. Submission never breaks.
    """
    dummy_img = Image.new("RGB", (320, 240), color=(100, 100, 100))
    img_path = str(tmp_path / "test_road.jpg")
    dummy_img.save(img_path)

    res = run_road_detector(img_path)
    assert res["source"] == "yolo"
    assert res["evidence_level"] == "detected"
    assert res["fallback_used"] is True
    val = res["value"]
    assert val["available"] is False
    assert val["detections"] == []
    assert val["severity"] is None
    assert val["severity_score"] == 0.0


def test_cefap_image_source_integration():
    """
    CEFAP accepts image_source and includes it in signals output.
    """
    class MockDB:
        def __init__(self):
            self.cefap_results = self
            self.cefap_weights = self
            self.docs = []
        def find_one(self, *args, **kwargs):
            return None
        def update_one(self, query, update, upsert=False):
            self.docs.append((query, update))

    mock_db = MockDB()

    # 1. With YOLO evidence
    res_yolo = cefap_stage(mock_db, {
        "service": "roads",
        "text_severity": "medium",
        "image_severity": "high",
        "image_confidence": 0.85,
        "image_source": "yolo"
    })
    assert res_yolo["signals"]["image_source"] == "yolo"
    assert res_yolo["signals"]["image_severity"] is not None

    # 2. With Gemini vision
    res_gemini = cefap_stage(mock_db, {
        "service": "roads",
        "text_severity": "medium",
        "image_severity": "medium",
        "image_confidence": 0.70,
        "image_source": "gemini_vision"
    })
    assert res_gemini["signals"]["image_source"] == "gemini_vision"

    # 3. _img helper
    ie = _img("high", 0.9, image_source="yolo")
    assert ie["source"] == "yolo"
    assert ie["score"] == 0.75


def test_real_model_loading_and_inference_if_present(tmp_path):
    """
    Exit Gate: Verifies ONNX session loading when a valid model exists.
    Tests on the baseline COCO YOLOv8n model present in ml/models/.
    """
    baseline_onnx = os.path.join(os.path.dirname(__file__), "..", "ml", "models", "_baseline_coco_yolov8n.onnx")
    if not os.path.exists(baseline_onnx):
        pytest.skip("_baseline_coco_yolov8n.onnx not present in local workspace")

    # Verify model size > MIN_MODEL_BYTES
    size = os.path.getsize(baseline_onnx)
    assert size > MIN_MODEL_BYTES

    # Load session
    sess = load_model("road_detector", custom_path=baseline_onnx)
    assert sess is not None

    # Run inference on synthetic test image
    img = Image.new("RGB", (640, 640), color=(128, 128, 128))
    img_path = str(tmp_path / "test_eval.jpg")
    img.save(img_path)

    res = run_road_detector(img_path, session_override=sess)
    assert res["source"] == "yolo"
    assert res["evidence_level"] == "detected"
    assert res["fallback_used"] is False
    assert res["value"]["available"] is True
    assert isinstance(res["value"]["detections"], list)


def test_evaluation_report_committed():
    """
    Exit Gate: Verifies committed evaluation report exists, is valid JSON,
    contains required metrics, and is flagged synthetic per Rule R10.
    """
    report_path = os.path.join(os.path.dirname(__file__), "..", "ml", "reports", "road_detector_evaluation.json")
    assert os.path.exists(report_path), "Evaluation report must be committed to ml/reports/"

    with open(report_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "overall_metrics" in data
    assert "mAP50" in data["overall_metrics"]
    assert "per_class_metrics" in data
    assert "D40" in data["per_class_metrics"]
    assert "cpu_latency" in data
    assert "mean_ms" in data["cpu_latency"]
    assert data.get("synthetic") is True

