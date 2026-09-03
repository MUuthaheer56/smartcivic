"""
Road damage detector module.
Supports YOLOv8 detection if model weights exist, otherwise returns a transparent simulation status.
"""
import io
import os
from PIL import Image

MODEL_PATH = "yolov8n-rdd.pt"

def detect_road_damage(image_data: bytes) -> dict:
    """
    Detect road damage using YOLOv8 if weights file exists,
    otherwise fallback cleanly to simulation mode.
    """
    try:
        img = Image.open(io.BytesIO(image_data))
        width, height = img.size
    except Exception:
        raise ValueError("Invalid image file payload")

    if os.path.exists(MODEL_PATH):
        try:
            from ultralytics import YOLO
            model = YOLO(MODEL_PATH)
            results = model(img)
            if results and len(results[0].boxes) > 0:
                box = results[0].boxes[0]
                cls_id = int(box.cls[0])
                cls_name = model.names.get(cls_id, "pothole")
                conf = float(box.conf[0])
                xyxy = box.xyxy[0].tolist()
                return {
                    "is_simulation": False,
                    "detected_class": cls_name,
                    "confidence": round(conf, 3),
                    "bounding_box": {
                        "x1": int(xyxy[0]),
                        "y1": int(xyxy[1]),
                        "x2": int(xyxy[2]),
                        "y2": int(xyxy[3])
                    },
                    "message": "Detection performed using YOLOv8 weights."
                }
        except Exception as e:
            return {
                "is_simulation": True,
                "detected_class": "unknown",
                "confidence": 0.0,
                "message": f"YOLOv8 execution error: {e}. Running in simulation mode."
            }

    return {
        "is_simulation": True,
        "detected_class": "pothole",
        "confidence": 0.0,
        "bounding_box": {"x1": 0, "y1": 0, "x2": width, "y2": height},
        "message": "Model weights (yolov8n-rdd.pt) not found. Running in simulation mode."
    }
