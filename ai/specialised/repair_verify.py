"""
SmartCivic — Repair Verification System via Image Comparison
"""
import cv2
import numpy as np
from skimage.metrics import structural_similarity as ssim

SSIM_CHANGE_THRESHOLD = 0.15 # >=15% structural change = repair detected

def compare_before_after_images(before_path: str, after_path: str) -> dict:
    """
    Computes Structural Similarity Index (SSIM) between the complaint's original image
    and the worker's after-photo. Returns repair_detected=True if SSIM change exceeds
    the threshold.
    """
    before = cv2.imread(before_path)
    after = cv2.imread(after_path)
    
    if before is None or after is None:
        return {
            "similarity": 1.0,
            "change_score": 0.0,
            "repair_detected": False,
            "confidence": 0,
            "result": "UNCERTAIN"
        }
        
    # Resize to common size for comparison
    target = (300, 300)
    before_r = cv2.resize(before, target)
    after_r = cv2.resize(after, target)
    
    # Convert to grayscale for SSIM
    before_g = cv2.cvtColor(before_r, cv2.COLOR_BGR2GRAY)
    after_g = cv2.cvtColor(after_r, cv2.COLOR_BGR2GRAY)
    
    score, _ = ssim(before_g, after_g, full=True)
    change = 1.0 - score
    repair_detected = change >= SSIM_CHANGE_THRESHOLD
    
    confidence = int(min(100, (change / max(SSIM_CHANGE_THRESHOLD, 0.01)) * 70))
    
    if change >= SSIM_CHANGE_THRESHOLD * 1.5:
        result = "PASS"
    elif change >= SSIM_CHANGE_THRESHOLD * 0.5:
        result = "UNCERTAIN"
    else:
        result = "FAIL"
        
    return {
        "similarity": round(float(score), 3),
        "change_score": round(float(change), 3),
        "repair_detected": repair_detected,
        "confidence": confidence,
        "result": result
    }
