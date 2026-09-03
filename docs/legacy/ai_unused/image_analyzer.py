"""
SmartCivic AI — Image Quality Gate & Visual Severity Scorer
Uses PIL/Pillow only — no additional ML dependencies required.
"""
import math
from PIL import Image, ImageStat, ImageFilter
from io import BytesIO


def _laplacian_variance(img: Image.Image) -> float:
    """Estimate image sharpness via Laplacian variance proxy using PIL."""
    gray = img.convert('L')
    # Apply a crude Laplacian-like kernel via subtract of blurred from original
    blurred = gray.filter(ImageFilter.GaussianBlur(radius=2))
    diff_pixels = [abs(a - b) for a, b in zip(list(gray.getdata()), list(blurred.getdata()))]
    n = len(diff_pixels)
    mean_diff = sum(diff_pixels) / n
    variance = sum((x - mean_diff) ** 2 for x in diff_pixels) / n
    return variance


def _mean_luminance(img: Image.Image) -> float:
    """Return mean luminance of the image (0–255)."""
    gray = img.convert('L')
    stat = ImageStat.Stat(gray)
    return stat.mean[0]


def _resolution_score(img: Image.Image) -> float:
    """Score 0-1 based on resolution. 480p = 0.5, 720p = 1.0."""
    min_dim = min(img.width, img.height)
    return min(1.0, min_dim / 720.0)


def analyze_image(image_bytes: bytes) -> dict:
    """
    Run quality gate and severity estimation on uploaded issue image.
    
    Returns:
        {
            "passed": bool,
            "reject_reason": str | None,
            "sharpness": float,        # Laplacian variance proxy
            "luminance": float,        # mean brightness 0-255
            "resolution_score": float, # 0.0 - 1.0
            "estimated_severity": int, # 1-5
            "confidence": str          # "high" | "medium" | "low"
        }
    """
    try:
        img = Image.open(BytesIO(image_bytes))
    except Exception:
        return {"passed": False, "reject_reason": "Cannot open image file", "estimated_severity": 3, "confidence": "low"}

    # Strip EXIF by re-saving through PIL buffer (privacy + security)
    buf = BytesIO()
    rgb = img.convert('RGB')
    rgb.save(buf, 'JPEG')
    buf.seek(0)
    img = Image.open(buf)

    sharpness = _laplacian_variance(img)
    luminance = _mean_luminance(img)
    res_score = _resolution_score(img)

    # Quality gate thresholds
    if sharpness < 20.0:
        return {
            "passed": False,
            "reject_reason": "Image is too blurry. Please upload a clearer photo.",
            "sharpness": round(sharpness, 2),
            "luminance": round(luminance, 2),
            "resolution_score": round(res_score, 2),
            "estimated_severity": 3,
            "confidence": "low"
        }
    if luminance < 25.0:
        return {
            "passed": False,
            "reject_reason": "Image is too dark. Please upload a better-lit photo.",
            "sharpness": round(sharpness, 2),
            "luminance": round(luminance, 2),
            "resolution_score": round(res_score, 2),
            "estimated_severity": 3,
            "confidence": "low"
        }
    if res_score < 0.4:
        return {
            "passed": False,
            "reject_reason": "Image resolution is too low (minimum 480p required).",
            "sharpness": round(sharpness, 2),
            "luminance": round(luminance, 2),
            "resolution_score": round(res_score, 2),
            "estimated_severity": 3,
            "confidence": "low"
        }

    # Visual severity estimation (1-5) based on image quality signals
    # Heuristic: very dark + low sharpness = worse condition
    darkness_factor = max(0.0, (128.0 - luminance) / 128.0)   # 0=bright, 1=dark
    blur_factor = max(0.0, 1.0 - min(1.0, sharpness / 300.0)) # 0=sharp, 1=blurry

    raw_score = 1.0 + (darkness_factor * 2.0) + (blur_factor * 2.0)
    estimated_severity = max(1, min(5, round(raw_score)))

    # Confidence based on resolution
    if res_score >= 0.9:
        confidence = "high"
    elif res_score >= 0.6:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "passed": True,
        "reject_reason": None,
        "sharpness": round(sharpness, 2),
        "luminance": round(luminance, 2),
        "resolution_score": round(res_score, 2),
        "estimated_severity": estimated_severity,
        "confidence": confidence
    }
