"""
SmartCivic+ — YOLO Vision Detection Service Wrapper
Exposes a stable run_yolo(image_path) contract for the AI pipeline, backed by
the ml/yolo_runner.py ONNX inference module.  Always returns a dict; degrades
gracefully to confidence=0 when the ONNX model is a placeholder or missing.
"""
import os
import logging
from config import Config

logger = logging.getLogger(__name__)

_DEFECT_CLASS_BY_TYPE = {
    "pothole":       "D40",
    "road_damage":   "D20",
    "crack_long":    "D00",
    "crack_trans":   "D10",
    "crosswalk":     "D43",
    "white_line":    "D44",
}

def _model_is_real() -> bool:
    p = getattr(Config, "YOLO_MODEL_PATH", "ml/models/pothole_yolov8n.onnx")
    return os.path.exists(p) and os.path.getsize(p) > 100_000

def run_yolo(image_path: str) -> dict:
    """
    Runs the local YOLO ONNX detector and returns a pipeline-shaped result.

    Returns a dict with (at minimum):
      - confidence: float in [0, 1]
      - defect_class: str, one of the DEFECT_EVIDENCE_MAP keys (D00..D44) or ""
      - available: bool
      - issue_type: str or None
      - bbox_area: float, estimated bounding-box area fraction (0..1) or 0.0
    """
    if not image_path or not os.path.exists(image_path):
        return {
            "available": False,
            "confidence": 0.0,
            "defect_class": "",
            "issue_type": None,
            "bbox_area": 0.0,
            "reason": "image_missing",
        }

    if not _model_is_real():
        return {
            "available": False,
            "confidence": 0.0,
            "defect_class": "",
            "issue_type": None,
            "bbox_area": 0.0,
            "reason": "onnx_model_placeholder_or_missing",
        }

    try:
        from ml.yolo_runner import run_yolo_inference
        raw = run_yolo_inference(image_path) or {}
    except Exception as exc:
        logger.warning("yolo_service.run_yolo import/inference exception: %s", exc)
        return {
            "available": False,
            "confidence": 0.0,
            "defect_class": "",
            "issue_type": None,
            "bbox_area": 0.0,
            "reason": f"inference_exception:{type(exc).__name__}",
        }

    available = bool(raw.get("available"))
    conf = float(raw.get("confidence") or 0.0)
    issue_type = raw.get("issue_type") or ""
    defect_class = _DEFECT_CLASS_BY_TYPE.get(issue_type,
        "D40" if issue_type == "pothole" else "D20" if issue_type else "")
    bbox_area = float(raw.get("bbox_area") or (0.07 if conf > 0.70 else 0.03))

    return {
        "available": available,
        "confidence": conf,
        "defect_class": defect_class,
        "issue_type": issue_type,
        "bbox_area": bbox_area,
        "severity": raw.get("severity"),
        "category": raw.get("category"),
    }
