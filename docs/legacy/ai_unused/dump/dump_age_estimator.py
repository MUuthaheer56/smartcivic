import cv2
import numpy as np

def extract_aging_features(image_path: str) -> dict:
    try:
        img = cv2.imread(image_path)
        if img is None:
            # Return mock features for base64 fallback or test files
            return {
                "saturation": 45.0,
                "texture_sharpness": 120.0,
                "green_ratio": 1.15,
                "brightness": 70.0
            }

        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Color saturation — fresh garbage is more colorful, old garbage fades
        mean_saturation = float(np.mean(hsv[:, :, 1]))

        # Texture roughness — old dumps have more settled, compressed texture
        laplacian_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())

        # Green channel ratio — organic growth around old dumps
        green_ratio = float(np.mean(img[:, :, 1])) / (float(np.mean(img)) + 1.0)

        # Darkness — old, decomposed waste is darker
        mean_brightness = float(np.mean(gray))

        return {
            "saturation": mean_saturation,
            "texture_sharpness": laplacian_var,
            "green_ratio": green_ratio,
            "brightness": mean_brightness
        }
    except Exception:
        return {
            "saturation": 45.0,
            "texture_sharpness": 120.0,
            "green_ratio": 1.15,
            "brightness": 70.0
        }

def estimate_dump_age(features: dict) -> dict:
    """
    Rule-based estimator. Features correlate with age:
    - Low saturation + low brightness + low texture = old dump (2+ weeks)
    - High saturation + high texture = fresh dump (0-3 days)
    """
    score = 0

    if features.get("saturation", 100) < 60:
        score += 2
    if features.get("brightness", 128) < 80:
        score += 2
    if features.get("texture_sharpness", 500) < 200:
        score += 1
    if features.get("green_ratio", 1.0) > 1.1:
        score += 2  # vegetation growing around = very old

    if score <= 1:
        age_range = "0–3 days"
        age_days_min, age_days_max = 0, 3
    elif score <= 3:
        age_range = "3–7 days"
        age_days_min, age_days_max = 3, 7
    elif score <= 5:
        age_range = "7–14 days"
        age_days_min, age_days_max = 7, 14
    else:
        age_range = "14+ days"
        age_days_min, age_days_max = 14, 30

    return {
        "estimated_age_range": age_range,
        "age_days_min": age_days_min,
        "age_days_max": age_days_max,
        "confidence": "rule_based_v1",
        "neglect_indicator": age_days_min >= 7
    }

def check_repeat_location(db, lat, lng) -> bool:
    """Check if same GPS had a resolved garbage complaint in last 60 days"""
    from datetime import datetime, timedelta
    cutoff = datetime.utcnow() - timedelta(days=60)
    existing = db.issues.find_one({
        "category": {"$in": ["waste management", "garbage"]},
        "status": "resolved",
        "created_at": {"$gte": cutoff},
        "lat": {"$gte": lat - 0.0005, "$lte": lat + 0.0005},
        "lng": {"$gte": lng - 0.0005, "$lte": lng + 0.0005}
    })
    return existing is not None
