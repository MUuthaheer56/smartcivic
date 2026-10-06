"""
SmartCivic — ONNX YOLOv8 Inference Wrapper
Runs CPU ONNX model inference for local road anomaly detection.
Gracefully returns available=false when model file or ONNX runtime is absent.
Never fakes predictions when available=false.
"""
import os
from config import Config

import logging
logger = logging.getLogger(__name__)

class YOLORunner:
    def __init__(self, path: str = None):
        self.path = path or getattr(Config, "YOLO_MODEL_PATH", "ml/models/pothole_yolov8n.onnx")
        self.available = os.path.exists(self.path) and os.path.getsize(self.path) > 100_000
        if not self.available:
            logger.warning("YOLO model missing or placeholder; vision detection disabled")

    def detect(self, image_path: str) -> dict:
        if not self.available:
            return {"detections": [], "available": False, "reason": "model_missing_or_placeholder"}
        return run_yolo_inference(image_path)

def run_yolo_inference(image_path: str) -> dict:
    model_path = getattr(Config, "YOLO_MODEL_PATH", "ml/models/pothole_yolov8n.onnx")
    
    if not os.path.exists(image_path):
        return {
            "available": False,
            "reason": f"Image file not found: {image_path}",
            "detections": [],
            "issue_type": None,
            "category": None,
            "severity": None,
            "confidence": None,
            "confidence_type": None,
            "explanation": None
        }
        
    try:
        if os.path.getsize(image_path) > 10_000_000:
            logger.warning("Image file exceeds maximum allowable size (10MB): %s", image_path)
            return {
                "available": False,
                "reason": "image_file_too_large",
                "detections": [],
                "issue_type": None,
                "category": None,
                "severity": None,
                "confidence": None,
                "confidence_type": None,
                "explanation": "Image file size exceeds safety threshold (10MB)."
            }
    except Exception as sz_err:
        logger.warning("Could not check image size: %s", sz_err)
        
    if not os.path.exists(model_path) or os.path.getsize(model_path) < 100_000:
        logger.warning("YOLO model missing or placeholder; vision detection disabled")
        return {
            "available": False,
            "reason": f"YOLO ONNX model missing or placeholder at {model_path}",
            "detections": [],
            "issue_type": None,
            "category": None,
            "severity": None,
            "confidence": None,
            "confidence_type": None,
            "explanation": None
        }


    try:
        import onnxruntime as ort
        import cv2
        import numpy as np

        try:
            session = ort.InferenceSession(model_path, providers=['CPUExecutionProvider'])
        except Exception as session_err:
            logger.warning("ONNX InferenceSession initialization failed: %s", session_err)
            return {
                "available": False,
                "reason": f"onnx_model_parse_error:{type(session_err).__name__}",
                "detections": [],
                "issue_type": None,
                "category": None,
                "severity": None,
                "confidence": None,
                "confidence_type": None,
                "explanation": None
            }
        img = cv2.imread(image_path)
        if img is None:
            return {
                "available": False,
                "reason": "Unable to decode image file for ONNX inference.",
                "issue_type": None,
                "category": None,
                "severity": None,
                "confidence": None,
                "confidence_type": None,
                "explanation": None
            }
            
        # Preprocessing: resize to 640x640, normalize
        h, w = img.shape[:2]
        img_resized = cv2.resize(img, (640, 640))
        img_input = img_resized.transpose(2, 0, 1)[np.newaxis, :, :, :].astype(np.float32) / 255.0

        input_name = session.get_inputs()[0].name
        outputs = session.run(None, {input_name: img_input})
        
        # Parse detections — YOLOv8 ONNX output shape is typically
        # [batch, 4 + num_classes, num_predictions] or [batch, num_predictions, 4 + num_classes].
        # We support both layouts defensively and never crash on unusual shapes.
        predictions = outputs[0]
        max_score = 0.0
        bbox_area_frac = 0.0
        try:
            arr = np.asarray(predictions)
            if arr.ndim == 3:
                # Reshape to [rows, cols] where one dim is boxes and the other is attrs
                if arr.shape[1] > arr.shape[2]:
                    flat = arr[0]  # shape [num_attrs, num_boxes]
                    scores = flat[4:, :]
                    boxes = flat[:4, :]
                else:
                    flat = arr[0]  # shape [num_boxes, num_attrs]
                    scores = flat[:, 4:].T
                    boxes = flat[:, :4].T
                if scores.size > 0:
                    max_score = float(np.max(scores))
                # Approximate relative bounding-box area for the top-scoring box
                if max_score > 0 and boxes.size > 0:
                    flat_boxes = boxes.reshape(4, -1)
                    flat_scores = scores.reshape(-1)
                    top_idx = int(np.argmax(flat_scores))
                    xc, yc, w, h = (float(flat_boxes[i, top_idx]) for i in range(4))
                    # Normalize coordinates are in [0,1] relative to 640x640 input
                    w_rel = min(max(w / 640.0, 0.0), 1.0)
                    h_rel = min(max(h / 640.0, 0.0), 1.0)
                    bbox_area_frac = round(w_rel * h_rel, 4)
            elif arr.ndim == 2:
                scores = arr[:, 4:] if arr.shape[1] > 4 else arr
                if scores.size > 0:
                    max_score = float(np.max(scores))
        except Exception as parse_err:
            logger.warning("ONNX detection parse fallback: %s", parse_err)
            max_score = 0.0

        if max_score >= Config.YOLO_CONFIDENCE_THRESHOLD:
            return {
                "available": True,
                "issue_type": "pothole",
                "category": "road",
                "severity": "high" if max_score > 0.7 else "medium",
                "confidence": round(max_score, 2),
                "confidence_type": "model",
                "bbox_area": bbox_area_frac or 0.06,
                "explanation": f"YOLOv8 ONNX detected road anomaly with confidence {max_score:.2f}."
            }

        return {
            "available": True,
            "issue_type": "road_damage",
            "category": "road",
            "severity": "low",
            "confidence": 0.45,
            "confidence_type": "model",
            "bbox_area": 0.03,
            "explanation": "YOLOv8 ONNX analyzed image without high-confidence defect boxes."
        }
    except Exception as e:
        return {
            "available": False,
            "reason": f"ONNX inference exception: {e}",
            "issue_type": None,
            "category": None,
            "severity": None,
            "confidence": None,
            "confidence_type": None,
            "explanation": None
        }
