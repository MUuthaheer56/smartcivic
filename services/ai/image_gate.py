"""
SmartCivic - Image Trust Gate
Evaluates uploaded complaint photos for blur, brightness, resolution, and reuse.
Returns a standardized AI result envelope. Never blocks an emergency.
"""
import os
import io
import time
from datetime import datetime
from typing import Optional, Union, Tuple, List, Dict, Any
import numpy as np
import cv2
from PIL import Image, ImageOps
from PIL.ExifTags import TAGS, GPSTAGS

from config import Config
from services.ai.envelope import make_ai_result


def _convert_to_degrees(value) -> float:
    """Converts GPS coordinate rational tuples to decimal degrees."""
    try:
        d = float(value[0])
        m = float(value[1])
        s = float(value[2])
        return d + (m / 60.0) + (s / 3600.0)
    except Exception:
        return 0.0


def extract_exif_gps(image_input: Union[str, bytes, io.BytesIO, Image.Image]) -> Optional[Dict[str, float]]:
    """
    Extracts latitude and longitude from image EXIF if present.
    Returns {'latitude': float, 'longitude': float} or None.
    """
    try:
        if isinstance(image_input, (str, os.PathLike)):
            if not os.path.exists(image_input):
                return None
            img = Image.open(image_input)
        elif isinstance(image_input, bytes):
            img = Image.open(io.BytesIO(image_input))
        elif hasattr(image_input, "read"):
            pos = image_input.tell() if hasattr(image_input, "tell") else 0
            img = Image.open(image_input)
            if hasattr(image_input, "seek"):
                image_input.seek(pos)
        elif isinstance(image_input, Image.Image):
            img = image_input
        else:
            return None

        exif = img.getexif()
        if not exif:
            return None

        gps_info = {}
        for tag_id, value in exif.items():
            tag_name = TAGS.get(tag_id, tag_id)
            if tag_name == "GPSInfo" or tag_id == 34853:
                if hasattr(exif, "get_ifd"):
                    try:
                        gps_ifd = exif.get_ifd(34853)
                        for gps_tag, val in gps_ifd.items():
                            sub_name = GPSTAGS.get(gps_tag, gps_tag)
                            gps_info[sub_name] = val
                    except Exception:
                        pass
                if not gps_info and isinstance(value, dict):
                    for gps_tag, val in value.items():
                        sub_name = GPSTAGS.get(gps_tag, gps_tag)
                        gps_info[sub_name] = val

        if not gps_info:
            return None

        lat_raw = gps_info.get("GPSLatitude")
        lat_ref = gps_info.get("GPSLatitudeRef", "N")
        lng_raw = gps_info.get("GPSLongitude")
        lng_ref = gps_info.get("GPSLongitudeRef", "E")

        if lat_raw and lng_raw:
            lat = _convert_to_degrees(lat_raw)
            if str(lat_ref).upper() != "N":
                lat = -lat
            lng = _convert_to_degrees(lng_raw)
            if str(lng_ref).upper() != "E":
                lng = -lng
            return {"latitude": round(lat, 6), "longitude": round(lng, 6)}
    except Exception:
        pass
    return None


def compute_dhash(img: Image.Image) -> str:
    """
    Computes 64-bit difference hash (dHash) as a 16-character hex string.
    Resizes image to 9x8 grayscale, compares adjacent columns.
    """
    gray = img.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    pixels = list(gray.getdata())
    diff = []
    for row in range(8):
        for col in range(8):
            pixel_left = pixels[row * 9 + col]
            pixel_right = pixels[row * 9 + col + 1]
            diff.append(1 if pixel_left > pixel_right else 0)
    decimal_val = 0
    for bit in diff:
        decimal_val = (decimal_val << 1) | bit
    return f"{decimal_val:016x}"


def hamming_distance(hash1: str, hash2: str) -> int:
    """Calculates Hamming distance between two 16-hex-character hashes."""
    try:
        val1 = int(hash1, 16)
        val2 = int(hash2, 16)
        return bin(val1 ^ val2).count("1")
    except Exception:
        return 64


def compute_blur_score(gray_np: np.ndarray) -> float:
    """Computes variance of Laplacian on grayscale image array."""
    try:
        return float(cv2.Laplacian(gray_np, cv2.CV_64F).var())
    except Exception:
        return 0.0


def compute_brightness_score(gray_np: np.ndarray) -> float:
    """Computes mean grayscale pixel intensity [0.0, 255.0]."""
    try:
        return float(np.mean(gray_np))
    except Exception:
        return 128.0


def _load_image(image_input: Union[str, bytes, io.BytesIO, Image.Image]) -> Tuple[Optional[Image.Image], Optional[np.ndarray]]:
    """Loads image into PIL Image and Grayscale NumPy array."""
    try:
        if isinstance(image_input, Image.Image):
            pil_img = image_input
        elif isinstance(image_input, (str, os.PathLike)):
            if not os.path.exists(image_input):
                return None, None
            pil_img = Image.open(image_input)
        elif isinstance(image_input, bytes):
            pil_img = Image.open(io.BytesIO(image_input))
        elif hasattr(image_input, "read"):
            pos = image_input.tell() if hasattr(image_input, "tell") else 0
            data = image_input.read()
            if hasattr(image_input, "seek"):
                image_input.seek(pos)
            pil_img = Image.open(io.BytesIO(data))
        else:
            return None, None

        pil_img = ImageOps.exif_transpose(pil_img)
        gray_np = np.array(pil_img.convert("L"))
        return pil_img, gray_np
    except Exception:
        return None, None


def evaluate_image_quality(
    image_input: Union[str, bytes, io.BytesIO, Image.Image],
    issue_id: Optional[str] = None,
    user_id: Optional[str] = None,
    db: Any = None
) -> Dict[str, Any]:
    """
    Evaluates image quality against configured thresholds:
    - Min resolution: IMAGE_GATE_MIN_WIDTH, IMAGE_GATE_MIN_HEIGHT
    - Blur threshold: IMAGE_GATE_BLUR_THRESHOLD
    - Dark threshold: IMAGE_GATE_DARK_THRESHOLD
    - Overexposed threshold: IMAGE_GATE_OVEREXPOSED_THRESHOLD
    - Perceptual reuse: IMAGE_GATE_HASH_HAMMING_THRESHOLD vs existing hashes in db

    Returns a standardized AI result envelope.
    """
    t0 = time.time()
    pil_img, gray_np = _load_image(image_input)
    if pil_img is None or gray_np is None:
        latency = int((time.time() - t0) * 1000)
        return make_ai_result(
            value={
                "passed": False,
                "issues": ["unreadable_or_corrupt"],
                "is_blurry": False,
                "is_dark": False,
                "is_overexposed": False,
                "is_too_small": False,
                "is_duplicate_photo": False,
                "metrics": {},
                "reused_issue_ids": [],
                "clarification_message": "Could not read image. Please upload a valid, clear image."
            },
            confidence=0.0,
            source="rules",
            model_version="image_gate_v1",
            evidence_level="detected",
            fallback_used=True,
            latency_ms=latency,
            error="Unable to decode image"
        )

    width, height = pil_img.size
    min_w = getattr(Config, "IMAGE_GATE_MIN_WIDTH", 320)
    min_h = getattr(Config, "IMAGE_GATE_MIN_HEIGHT", 240)
    blur_thresh = getattr(Config, "IMAGE_GATE_BLUR_THRESHOLD", 80.0)
    dark_thresh = getattr(Config, "IMAGE_GATE_DARK_THRESHOLD", 35.0)
    overexposed_thresh = getattr(Config, "IMAGE_GATE_OVEREXPOSED_THRESHOLD", 235.0)
    hamming_thresh = getattr(Config, "IMAGE_GATE_HASH_HAMMING_THRESHOLD", 5)

    issues: List[str] = []
    
    # 1. Resolution Check
    is_too_small = (width < min_w or height < min_h)
    if is_too_small:
        issues.append("too_small")

    # 2. Blur Check
    blur_score = compute_blur_score(gray_np)
    is_blurry = blur_score < blur_thresh
    if is_blurry:
        issues.append("blurry")

    # 3. Brightness Check
    brightness_score = compute_brightness_score(gray_np)
    is_dark = brightness_score < dark_thresh
    is_overexposed = brightness_score > overexposed_thresh
    if is_dark:
        issues.append("dark")
    elif is_overexposed:
        issues.append("overexposed")

    # 4. Perceptual Hash & Duplicate Detection
    dhash = compute_dhash(pil_img)
    is_duplicate_photo = False
    reused_issue_ids: List[str] = []

    if db is not None:
        try:
            # Query existing image hashes
            existing_records = list(db.image_hashes.find(
                {},
                {"hash": 1, "issue_id": 1, "user_id": 1}
            ).limit(500))

            for rec in existing_records:
                rec_hash = rec.get("hash")
                rec_issue_id = str(rec.get("issue_id", ""))
                rec_user_id = str(rec.get("user_id", ""))

                # Ignore comparison with the current issue/user itself
                if issue_id and rec_issue_id == str(issue_id):
                    continue

                if rec_hash:
                    dist = hamming_distance(dhash, rec_hash)
                    if dist <= hamming_thresh:
                        is_duplicate_photo = True
                        if rec_issue_id and rec_issue_id not in reused_issue_ids:
                            reused_issue_ids.append(rec_issue_id)
        except Exception:
            pass

    if is_duplicate_photo:
        issues.append("duplicate_photo")

    passed = (len(issues) == 0)

    # Human-friendly clarification message for CTVE modal
    msg_parts = []
    if is_blurry:
        msg_parts.append("The photo appears blurry")
    if is_dark:
        msg_parts.append("The photo is too dark")
    if is_overexposed:
        msg_parts.append("The photo is overexposed")
    if is_too_small:
        msg_parts.append("The photo resolution is too small")
    if is_duplicate_photo:
        ref_text = f" (similar to issue #{reused_issue_ids[0]})" if reused_issue_ids else ""
        msg_parts.append(f"This photo appears identical to an existing report{ref_text}")

    if msg_parts:
        clarification_msg = " and ".join(msg_parts) + ". Please upload a clearer photo to help us verify and resolve this issue."
    else:
        clarification_msg = None

    latency = int((time.time() - t0) * 1000)

    return make_ai_result(
        value={
            "passed": passed,
            "issues": issues,
            "is_blurry": is_blurry,
            "is_dark": is_dark,
            "is_overexposed": is_overexposed,
            "is_too_small": is_too_small,
            "is_duplicate_photo": is_duplicate_photo,
            "metrics": {
                "blur": round(blur_score, 2),
                "brightness": round(brightness_score, 2),
                "width": width,
                "height": height,
                "hash": dhash
            },
            "reused_issue_ids": reused_issue_ids,
            "clarification_message": clarification_msg
        },
        confidence=1.0,
        source="rules",
        model_version="image_gate_v1",
        evidence_level="detected",
        fallback_used=False,
        latency_ms=latency
    )


def store_image_hash(db: Any, hash_str: str, issue_id: str, user_id: Optional[str] = None, metrics: Optional[dict] = None) -> bool:
    """Stores perceptual hash in db.image_hashes."""
    if db is None or not hash_str or not issue_id:
        return False
    try:
        doc = {
            "hash": hash_str,
            "issue_id": str(issue_id),
            "user_id": str(user_id) if user_id else None,
            "created_at": datetime.utcnow(),
            "metrics": metrics or {}
        }
        db.image_hashes.insert_one(doc)
        return True
    except Exception:
        return False

