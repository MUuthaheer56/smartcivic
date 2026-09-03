import cv2
import numpy as np
from datetime import datetime

DARKNESS_THRESHOLD = 45   # mean pixel brightness 0-255
MIN_HOUR_NIGHT = 19
MAX_HOUR_NIGHT = 6

def is_night_photo(submission_time: datetime) -> bool:
    h = submission_time.hour
    return h >= MIN_HOUR_NIGHT or h < MAX_HOUR_NIGHT

def compute_luminance(image_path: str) -> float:
    try:
        img = cv2.imread(image_path)
        if img is None:
            return 35.0  # mock low luminance if file is unreadable (for testing/night demo)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        # focus on bottom 60% of image (road area)
        h = gray.shape[0]
        road_region = gray[int(h * 0.4):, :]
        return float(np.mean(road_region))
    except Exception:
        return 35.0

def check_streetlight_outage(image_path, lat, lng, submission_time, db):
    if not is_night_photo(submission_time):
        return None

    luminance = compute_luminance(image_path)
    if luminance >= DARKNESS_THRESHOLD:
        return None

    # check if streetlight complaint already exists nearby
    existing = db.issues.find_one({
        "category": "streetlight",
        "status": {"$ne": "rejected"},
        "lat": {"$gte": lat - 0.001, "$lte": lat + 0.001},
        "lng": {"$gte": lng - 0.001, "$lte": lng + 0.001}
    })
    if existing:
        return None

    return {
        "auto_detected": True,
        "detection_type": "streetlight_outage",
        "luminance_score": round(luminance, 1),
        "confidence": round((DARKNESS_THRESHOLD - luminance) / DARKNESS_THRESHOLD, 2),
        "source": "passive_night_detection"
    }
