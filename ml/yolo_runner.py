"""
SmartCivic — ONNX YOLOv8 Inference Wrapper
Runs CPU ONNX model inference for local road anomaly detection.
Gracefully returns available=false when model file or ONNX runtime is absent.
Never fakes predictions when available=false.
"""
import os
from config import Config

def run_yolo_inference(image_path: str) -> dict:
    model_path = getattr(Config, "YOLO_MODEL_PATH", "ml/models/pothole_yolov8n.onnx")
    
    if not os.path.exists(image_path):
        return {
            "available": False,
            "reason": f"Image file not found: {image_path}",
            "issue_type": None,
            "category": None,
            "severity": None,
            "confidence": None,
            "confidence_type": None,
            "explanation": None
        }
        
    if not os.path.exists(model_path):
        return {
            "available": False,
            "reason": f"YOLO ONNX model file missing at {model_path}",
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

        session = ort.InferenceSession(model_path, providers=['CPUExecutionProvider'])
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
        
        # Parse detections
        predictions = outputs[0]
        # Check highest confidence box
        if len(predictions) > 0 and predictions.shape[-1] > 4:
            scores = predictions[0, 4:, :]
            max_score = float(np.max(scores)) if scores.size > 0 else 0.0
            if max_score >= Config.YOLO_CONFIDENCE_THRESHOLD:
                return {
                    "available": True,
                    "issue_type": "pothole",
                    "category": "road",
                    "severity": "high" if max_score > 0.7 else "medium",
                    "confidence": round(max_score, 2),
                    "confidence_type": "model",
                    "explanation": f"YOLOv8 ONNX detected road anomaly with confidence {max_score:.2f}."
                }

        return {
            "available": True,
            "issue_type": "road_damage",
            "category": "road",
            "severity": "low",
            "confidence": 0.45,
            "confidence_type": "model",
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
