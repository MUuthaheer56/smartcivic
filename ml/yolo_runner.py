"""
SmartCivic — ONNX YOLO Road Defect Detector
Implements strict integrity verification (manifest, SHA256 checksum, metrics, class count)
and fails closed when vision is disabled or unevaluated.
Never fakes predictions when available=false.
"""
import os
import json
import hashlib
import logging
from config import Config

logger = logging.getLogger(__name__)
MODEL_DIR = os.path.join(os.path.dirname(__file__), "models")

def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def load_detector():
    """
    Validates model at load time and fails closed.
    Returns (session, manifest), 'ok' on success, or None, <reason> on failure.
    """
    if not getattr(Config, "VISION_ENABLED", False):
        return None, "vision_disabled"
        
    mpath = os.path.join(MODEL_DIR, "manifest.json")
    if not os.path.exists(mpath):
        return None, "no_manifest"
        
    try:
        with open(mpath, "r", encoding="utf-8") as mf:
            m = json.load(mf)
    except Exception as exc:
        logger.warning("Manifest parsing error: %s", exc)
        return None, "invalid_manifest"

    model_file = m.get("model_file")
    if not model_file:
        return None, "model_missing"
        
    fpath = os.path.join(MODEL_DIR, model_file)
    if not os.path.exists(fpath):
        return None, "model_missing"
        
    expected_hash = m.get("sha256")
    if not expected_hash or _sha256(fpath) != expected_hash:
        return None, "checksum_mismatch"
        
    # Refuse unevaluated models without recorded mAP metrics
    if not m.get("metrics", {}).get("map50"):
        return None, "model_not_evaluated"
        
    try:
        import onnxruntime as ort
        sess = ort.InferenceSession(fpath, providers=["CPUExecutionProvider"])
    except Exception as exc:
        logger.warning("ONNX InferenceSession failed to load: %s", exc)
        return None, f"onnx_init_failed:{type(exc).__name__}"

    n_out = sess.get_outputs()[0].shape  # e.g. [1, 4+num_classes, 8400]
    expected_classes = m.get("classes", [])
    if len(n_out) > 1 and n_out[1] != 4 + len(expected_classes):
        return None, "class_count_mismatch"

    return (sess, m), "ok"


class YOLORunner:
    def __init__(self, path: str = None):
        sess_tuple, status = load_detector()
        self.available = sess_tuple is not None
        self.status = status

    def detect(self, image_path: str) -> dict:
        return run_yolo_inference(image_path)


def run_yolo_inference(image_path: str) -> dict:
    fallback_message = "Image analysis unavailable, your report was still recorded"
    
    if not image_path or not os.path.exists(image_path):
        return {
            "available": False,
            "reason": "image_file_not_found: file not found",
            "message": fallback_message,
            "detections": [],
            "issue_type": None,
            "category": None,
            "severity": None,
            "confidence": 0.0,
            "confidence_type": None,
            "explanation": fallback_message
        }

    try:
        if os.path.getsize(image_path) > 10_000_000:
            logger.warning("Image file exceeds maximum allowable size (10MB): %s", image_path)
            return {
                "available": False,
                "reason": "image_file_too_large",
                "message": fallback_message,
                "detections": [],
                "issue_type": None,
                "category": None,
                "severity": None,
                "confidence": 0.0,
                "confidence_type": None,
                "explanation": fallback_message
            }
    except Exception:
        pass

    detector_res, status = load_detector()
    if detector_res is None:
        return {
            "available": False,
            "reason": status,
            "message": fallback_message,
            "detections": [],
            "issue_type": None,
            "category": None,
            "severity": None,
            "confidence": 0.0,
            "confidence_type": None,
            "explanation": fallback_message
        }

    session, manifest = detector_res
    allowed_classes = manifest.get("classes", [])

    try:
        import cv2
        import numpy as np

        img = cv2.imread(image_path)
        if img is None:
            return {
                "available": False,
                "reason": "image_decode_failed",
                "message": fallback_message,
                "detections": [],
                "issue_type": None,
                "category": None,
                "severity": None,
                "confidence": 0.0,
                "confidence_type": None,
                "explanation": fallback_message
            }

        input_size = int(manifest.get("input_size", 640))
        img_resized = cv2.resize(img, (input_size, input_size))
        img_input = img_resized.transpose(2, 0, 1)[np.newaxis, :, :, :].astype(np.float32) / 255.0

        input_name = session.get_inputs()[0].name
        outputs = session.run(None, {input_name: img_input})
        predictions = outputs[0]

        max_score = 0.0
        top_defect_class = None
        bbox_area_frac = 0.0

        arr = np.asarray(predictions)
        if arr.ndim == 3:
            flat = arr[0]
            if flat.shape[0] < flat.shape[1]:
                boxes = flat[:4, :]
                scores = flat[4:, :]
            else:
                boxes = flat[:, :4].T
                scores = flat[:, 4:].T

            if scores.size > 0:
                max_scores_per_box = np.max(scores, axis=0)
                best_box_idx = int(np.argmax(max_scores_per_box))
                max_score = float(max_scores_per_box[best_box_idx])
                best_class_idx = int(np.argmax(scores[:, best_box_idx]))
                if best_class_idx < len(allowed_classes):
                    top_defect_class = allowed_classes[best_class_idx]
                if max_score > 0 and boxes.shape[1] > best_box_idx:
                    xc, yc, w, h = (float(boxes[i, best_box_idx]) for i in range(4))
                    w_rel = min(max(w / float(input_size), 0.0), 1.0)
                    h_rel = min(max(h / float(input_size), 0.0), 1.0)
                    bbox_area_frac = round(w_rel * h_rel, 4)

        if not top_defect_class or top_defect_class not in allowed_classes:
            return {
                "available": True,
                "reason": "no_supported_defects_found",
                "detections": [],
                "issue_type": None,
                "category": None,
                "severity": None,
                "confidence": 0.0,
                "confidence_type": "model",
                "bbox_area": 0.0,
                "explanation": "No road defects from supported classes detected in image."
            }

        conf_threshold = getattr(Config, "YOLO_CONFIDENCE_THRESHOLD", 0.40)
        if max_score >= conf_threshold:
            return {
                "available": True,
                "detections": [{
                    "class": top_defect_class,
                    "confidence": round(max_score, 2),
                    "bbox_area": bbox_area_frac
                }],
                "issue_type": top_defect_class,
                "category": "road",
                "severity": "high" if max_score > 0.70 else "medium",
                "confidence": round(max_score, 2),
                "confidence_type": "model",
                "bbox_area": bbox_area_frac or 0.05,
                "explanation": f"Detected {top_defect_class} with confidence {max_score:.2f}."
            }

        return {
            "available": True,
            "detections": [],
            "issue_type": top_defect_class,
            "category": "road",
            "severity": "low",
            "confidence": round(max_score, 2),
            "confidence_type": "model",
            "bbox_area": bbox_area_frac,
            "explanation": "Low-confidence anomaly detected below alert threshold."
        }
    except Exception as exc:
        logger.warning("ONNX inference exception: %s", exc)
        return {
            "available": False,
            "reason": f"inference_exception:{type(exc).__name__}",
            "message": fallback_message,
            "detections": [],
            "issue_type": None,
            "category": None,
            "severity": None,
            "confidence": 0.0,
            "confidence_type": None,
            "explanation": fallback_message
        }
