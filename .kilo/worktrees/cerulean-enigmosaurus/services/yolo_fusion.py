"""
SmartCivic v2 — YOLO Multimodal Fusion Service
Fuses ONNX CPU object detection bounding box signals with text classification to refine issue severity.
"""
from ml.yolo_runner import run_yolo_inference

SEVERITY_LEVELS = ["low", "medium", "high", "critical"]

DEFECT_EVIDENCE_MAP = {
    "D00": {"name": "longitudinal_crack",  "severity_signal": "low"},
    "D10": {"name": "transverse_crack",    "severity_signal": "low"},
    "D20": {"name": "alligator_crack",     "severity_signal": "medium"},
    "D40": {"name": "pothole",             "severity_signal": "high"},
    "D43": {"name": "crosswalk_blur",      "severity_signal": "low"},
    "D44": {"name": "white_line_blur",     "severity_signal": "low"},
}

def _upgrade_severity(severity: str) -> str:
    sev = (severity or "medium").lower()
    idx = SEVERITY_LEVELS.index(sev) if sev in SEVERITY_LEVELS else 1
    return SEVERITY_LEVELS[min(idx + 1, len(SEVERITY_LEVELS) - 1)]

def _downgrade_severity(severity: str) -> str:
    sev = (severity or "medium").lower()
    idx = SEVERITY_LEVELS.index(sev) if sev in SEVERITY_LEVELS else 1
    return SEVERITY_LEVELS[max(idx - 1, 0)]

def analyze_and_fuse(image_path: str, classification_prediction: dict) -> dict:
    """
    Runs ONNX YOLO inference on image and fuses visual evidence with text prediction.
    YOLO adjusts severity level — never overrides emergency or service category.
    """
    if not image_path:
        classification_prediction["visual_evidence"] = None
        return classification_prediction

    yolo_result = run_yolo_inference(image_path)

    if not yolo_result.get("available", False) or (yolo_result.get("confidence") or 0.0) < 0.40:
        classification_prediction["visual_evidence"] = None
        return classification_prediction

    conf = float(yolo_result.get("confidence") or 0.50)
    defect_cls = yolo_result.get("issue_type") or "D40"
    defect_info = DEFECT_EVIDENCE_MAP.get(defect_cls, {"name": "pothole", "severity_signal": "high"})
    bbox_area = float(yolo_result.get("bbox_area") or 0.06)
    size_signal = "large" if bbox_area > 0.05 else "small"

    visual_evidence = {
        "defect_name": defect_info.get("name", "road_anomaly"),
        "severity_signal": defect_info.get("severity_signal", "medium"),
        "yolo_confidence": conf,
        "size_signal": size_signal,
        "image_severity_score": round(conf * 10, 1),
    }

    # Dynamic severity adjustment for road complaints
    if classification_prediction.get("service") in ["roads", "road"]:
        current_sev = classification_prediction.get("severity", "medium")

        if (visual_evidence["severity_signal"] == "high" and conf > 0.70 and size_signal == "large"):
            classification_prediction["severity"] = _upgrade_severity(current_sev)
        elif (visual_evidence["severity_signal"] == "low" and conf > 0.80 and current_sev == "critical"):
            classification_prediction["severity"] = _downgrade_severity(current_sev)

    classification_prediction["visual_evidence"] = visual_evidence
    return classification_prediction
