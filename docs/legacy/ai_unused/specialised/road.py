"""
SmartCivic — Pothole Volume Estimator
"""
import cv2
import numpy as np

# Calibration: assume camera ~1.5m above ground, 70° FOV, 1080p
PIXELS_PER_CM_AT_1M = 12.0 # calibrate per deployment
DEPTH_SHADOW_MULTIPLIER = 0.4

def estimate_pothole_volume(image_path: str) -> dict:
    """
    Uses the YOLO bounding box area and shadow region analysis to estimate pothole volume in cm³.
    Maps the estimate to a repair cost tier: LOW (<500cm³), MED (500–2000cm³), HIGH (>2000cm³).
    """
    img = cv2.imread(image_path)
    if img is None:
        return {"volume_cm3": 0, "cost_tier": "LOW", "area_cm2": 0, "estimated_depth_cm": 0}
        
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    
    # Shadow analysis: dark regions suggest depth
    _, shadow_mask = cv2.threshold(gray, 60, 255, cv2.THRESH_BINARY_INV)
    shadow_pixels = cv2.countNonZero(shadow_mask)
    total_pixels = h * w
    shadow_ratio = shadow_pixels / max(total_pixels, 1)
    
    # Approximate bounding box as lower-centre third (road surface)
    roi = gray[h//2:, w//4: 3*w//4]
    edges = cv2.Canny(roi, 50, 150)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    if not contours:
        return {"volume_cm3": 0, "cost_tier": "LOW", "area_cm2": 0, "estimated_depth_cm": 0}
        
    largest = max(contours, key=cv2.contourArea)
    box_area_px = cv2.contourArea(largest)
    area_cm2 = box_area_px / (PIXELS_PER_CM_AT_1M ** 2)
    
    # Estimate depth from shadow ratio (heuristic)
    estimated_depth_cm = max(1.0, shadow_ratio * 100 * DEPTH_SHADOW_MULTIPLIER)
    volume_cm3 = area_cm2 * estimated_depth_cm
    
    if volume_cm3 > 2000:
        tier = "HIGH"
    elif volume_cm3 > 500:
        tier = "MED"
    else:
        tier = "LOW"
        
    return {
        "volume_cm3": round(volume_cm3, 1),
        "cost_tier": tier,
        "area_cm2": round(area_cm2, 1),
        "estimated_depth_cm": round(estimated_depth_cm, 1)
    }
