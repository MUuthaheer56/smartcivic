"""
SmartCivic - Real Road Damage Detector (RDD2022 YOLOv8n ONNX)
Loads YOLOv8 ONNX model via ModelRegistry, executes CPU inference,
and computes defect severity using the written provisional rubric.
Fails safely if model is missing, corrupt, or a placeholder.
"""
import os
import time
import logging
from typing import Optional, Dict, Any, List, Union
import numpy as np
import cv2
from PIL import Image

from config import Config
from services.ai.registry import registry, load_model, MIN_MODEL_BYTES
from services.ai.envelope import make_ai_result
from services.ai.severity_rubric import calculate_defect_severity, DEFECT_CLASSES

logger = logging.getLogger(__name__)

# Default RDD2022 classes
RDD_CLASS_NAMES = ["D00", "D10", "D20", "D40"]
CONFIDENCE_THRESHOLD = 0.25
NMS_THRESHOLD = 0.45


def _onnx_session_loader(model_path: str):
    """Loads ONNX inference session on CPU."""
    try:
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 2
        opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        return ort.InferenceSession(model_path, sess_options=opts, providers=["CPUExecutionProvider"])
    except Exception as e:
        logger.warning(f"[RoadDetector] Failed to create ONNX session for '{model_path}': {e}")
        return None


# Register road detector with registry
registry.register(
    name="road_detector",
    default_rel_path="models_artifacts/road_damage_v1.onnx",
    loader_fn=_onnx_session_loader
)


def _preprocess_image(image_input: Union[str, bytes, Image.Image, np.ndarray], target_size: int = 640):
    """
    Loads and normalizes image for YOLOv8 ONNX (NCHW format, RGB, 0.0 - 1.0).
    Returns (preprocessed_tensor, original_width, original_height).
    """
    if isinstance(image_input, (str, os.PathLike)):
        if not os.path.exists(image_input):
            return None, 0, 0
        img = Image.open(image_input).convert("RGB")
    elif isinstance(image_input, Image.Image):
        img = image_input.convert("RGB")
    elif isinstance(image_input, np.ndarray):
        img = Image.fromarray(image_input).convert("RGB")
    else:
        return None, 0, 0

    orig_w, orig_h = img.size
    # Resize keeping aspect ratio or direct resize
    img_resized = img.resize((target_size, target_size), Image.Resampling.BILINEAR)
    img_np = np.array(img_resized).astype(np.float32) / 255.0  # HWC
    img_np = np.transpose(img_np, (2, 0, 1))  # CHW
    img_tensor = np.expand_dims(img_np, axis=0)  # NCHW: 1, 3, 640, 640
    return img_tensor, orig_w, orig_h


def _get_active_session():
    """Attempts to load road detector session from registry with fallbacks."""
    # 0. Primary trained artifact in models_artifacts/road_detector/v1/model.onnx
    v1_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "models_artifacts", "road_detector", "v1", "model.onnx"))
    if os.path.exists(v1_path):
        session = load_model("road_detector", custom_path=v1_path)
        if session is not None:
            return session, v1_path

    # 1. Primary artifact path
    session = load_model("road_detector")
    if session is not None:
        return session, "models_artifacts/road_damage_v1.onnx"

    # 2. Check fallback path in ml/models/road_damage_v1.onnx
    ml_path = os.path.join(os.path.dirname(__file__), "..", "..", "ml", "models", "road_damage_v1.onnx")
    if os.path.exists(ml_path):
        session = load_model("road_detector", custom_path=ml_path)
        if session is not None:
            return session, ml_path

    # 3. Check Config.YOLO_MODEL_PATH if specified
    cfg_path = getattr(Config, "YOLO_MODEL_PATH", None)
    if cfg_path and os.path.exists(cfg_path):
        session = load_model("road_detector", custom_path=cfg_path)
        if session is not None:
            return session, cfg_path

    return None, None


def run_road_detector(
    image_input: Union[str, bytes, Image.Image, np.ndarray],
    conf_thresh: float = CONFIDENCE_THRESHOLD,
    session_override: Any = None
) -> Dict[str, Any]:
    """
    Executes road damage defect detection on CPU.
    Returns standardized AI envelope.
    Degrades cleanly if model is unavailable, corrupt, or a placeholder.
    """
    t0 = time.time()
    
    # Rule R5: Feature flag check (disabled by default) unless session override provided
    if not getattr(Config, "AI_LOCAL_DETECTOR_ENABLED", False) and not session_override:
        latency = int((time.time() - t0) * 1000)
        return make_ai_result(
            value={
                "available": False,
                "detections": [],
                "primary_defect": None,
                "defect_class": None,
                "severity": None,
                "severity_score": 0.0,
                "bbox_area_ratio": 0.0,
                "reason": "feature_flag_disabled"
            },
            confidence=0.0,
            source="yolo",
            model_version="yolov8n_rdd2022_v1",
            evidence_level="detected",
            fallback_used=True,
            latency_ms=latency,
            error="Road damage detector feature flag disabled"
        )

    session, model_path = (session_override, "override") if session_override else _get_active_session()
    if session is None:
        latency = int((time.time() - t0) * 1000)
        return make_ai_result(
            value={
                "available": False,
                "detections": [],
                "primary_defect": None,
                "defect_class": None,
                "severity": None,
                "severity_score": 0.0,
                "bbox_area_ratio": 0.0,
                "reason": "model_missing_or_placeholder"
            },
            confidence=0.0,
            source="yolo",
            model_version="yolov8n_rdd2022_v1",
            evidence_level="detected",
            fallback_used=True,
            latency_ms=latency,
            error="Road damage detector model file missing or placeholder"
        )

    try:
        # Determine target resolution from model input layer if fixed (e.g. 416 or 640)
        target_size = 416
        try:
            inp_shape = session.get_inputs()[0].shape
            if len(inp_shape) == 4 and isinstance(inp_shape[2], int) and inp_shape[2] > 0:
                target_size = inp_shape[2]
        except Exception:
            target_size = 416

        tensor, orig_w, orig_h = _preprocess_image(image_input, target_size=target_size)
        if tensor is None or orig_w == 0 or orig_h == 0:
            latency = int((time.time() - t0) * 1000)
            return make_ai_result(
                value={
                    "available": False,
                    "detections": [],
                    "primary_defect": None,
                    "defect_class": None,
                    "severity": None,
                    "severity_score": 0.0,
                    "bbox_area_ratio": 0.0,
                    "reason": "invalid_image"
                },
                confidence=0.0,
                source="yolo",
                model_version="yolov8n_rdd2022_v1",
                evidence_level="detected",
                fallback_used=True,
                latency_ms=latency,
                error="Could not decode image"
            )

        input_name = session.get_inputs()[0].name
        outputs = session.run(None, {input_name: tensor})
        output = outputs[0]  # shape: [1, 4 + num_classes, num_anchors] or transposed

        # YOLOv8 format standardisation
        if len(output.shape) == 3:
            if output.shape[1] < output.shape[2]:
                output = np.transpose(output, (0, 2, 1))
            output = output[0]  # [num_anchors, 4 + num_classes]

        boxes = []
        confidences = []
        class_ids = []

        scale_x = orig_w / float(target_size)
        scale_y = orig_h / float(target_size)

        for row in output:
            scores = row[4:]
            class_id = int(np.argmax(scores))
            confidence = float(scores[class_id])

            if confidence >= conf_thresh:
                # Bbox format in YOLO: cx, cy, w, h
                cx, cy, w, h = row[0:4]
                x = int((cx - (w / 2)) * scale_x)
                y = int((cy - (h / 2)) * scale_y)
                box_w = int(w * scale_x)
                box_h = int(h * scale_y)

                boxes.append([x, y, box_w, box_h])
                confidences.append(confidence)
                class_ids.append(class_id)

        indices = cv2.dnn.NMSBoxes(boxes, confidences, score_threshold=conf_thresh, nms_threshold=NMS_THRESHOLD)
        
        # Supported class mappings (trained model + standard RDD)
        TRAINED_CLASSES = ["Crack", "Pothole", "Surface Erosion"]

        detections: List[Dict[str, Any]] = []
        if len(indices) > 0:
            flat_indices = indices.flatten() if hasattr(indices, "flatten") else [indices[0]]
            img_area = float(orig_w * orig_h) if (orig_w * orig_h) > 0 else 1.0

            for idx in flat_indices:
                x, y, bw, bh = boxes[idx]
                cid = class_ids[idx]
                conf = round(float(confidences[idx]), 3)

                if cid < len(TRAINED_CLASSES):
                    cname = TRAINED_CLASSES[cid]
                    cls_code = "D40" if cname == "Pothole" else ("D00" if cname == "Crack" else "D20")
                    cls_name = cname
                else:
                    cls_code = RDD_CLASS_NAMES[cid] if cid < len(RDD_CLASS_NAMES) else f"D{cid:02d}"
                    cls_name = DEFECT_CLASSES.get(cls_code, f"defect_{cls_code}")
                
                box_area = max(0, bw) * max(0, bh)
                area_ratio = round(box_area / img_area, 4)
                sev, score = calculate_defect_severity(cls_code, area_ratio)

                detections.append({
                    "defect_code": cls_code,
                    "class_name": cls_name,
                    "confidence": conf,
                    "bbox": [x, y, bw, bh],
                    "area_ratio": area_ratio,
                    "severity": sev,
                    "severity_score": score
                })

        # Sort detections by severity score descending, then confidence
        detections.sort(key=lambda d: (d["severity_score"], d["confidence"]), reverse=True)

        if detections:
            top_det = detections[0]
            primary_code = top_det["defect_code"]
            primary_name = top_det["class_name"]
            overall_severity = top_det["severity"]
            overall_score = top_det["severity_score"]
            overall_conf = top_det["confidence"]
            max_area = max(d["area_ratio"] for d in detections)
        else:
            primary_code = None
            primary_name = None
            overall_severity = "low"
            overall_score = 0.10
            overall_conf = 0.50
            max_area = 0.0

        latency = int((time.time() - t0) * 1000)

        return make_ai_result(
            value={
                "available": True,
                "detections": detections,
                "detection_count": len(detections),
                "primary_defect": primary_name,
                "defect_class": primary_code,
                "severity": overall_severity,
                "severity_score": overall_score,
                "bbox_area_ratio": max_area
            },
            confidence=overall_conf,
            source="yolo",
            model_version="yolov8n_rdd2022_v1",
            evidence_level="detected",
            fallback_used=False,
            latency_ms=latency
        )

    except Exception as exc:
        logger.warning(f"[RoadDetector] Inference error: {exc}")
        latency = int((time.time() - t0) * 1000)
        return make_ai_result(
            value={
                "available": False,
                "detections": [],
                "primary_defect": None,
                "defect_class": None,
                "severity": None,
                "severity_score": 0.0,
                "bbox_area_ratio": 0.0,
                "reason": f"runtime_exception:{type(exc).__name__}"
            },
            confidence=0.0,
            source="yolo",
            model_version="yolov8n_rdd2022_v1",
            evidence_level="detected",
            fallback_used=True,
            latency_ms=latency,
            error=str(exc)
        )

