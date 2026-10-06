"""
SmartCivic v2 — Complaint Verification Pipeline
Computes composite confidence scores and determines verification status.
"""
from datetime import datetime

def compute_confidence_score(complaint: dict) -> float:
    """
    Composite confidence score 0.0 – 1.0.
    Components:
      - Resident verified:     +0.30
      - Photo evidence:        +0.25
      - AI analysis present:   +0.20
      - Support count:         up to +0.25 (5 supporters = max)
    """
    score = 0.0

    # Verified reporter
    if complaint.get("reporter_verified"):
        score += 0.30

    # Photo evidence
    photos = complaint.get("photos") or complaint.get("images") or []
    if photos and len(photos) > 0:
        score += 0.25

    # AI classification confidence
    ai_conf = float(complaint.get("ai_confidence", 0.0))
    if ai_conf >= 0.70:
        score += 0.20
    elif ai_conf >= 0.50:
        score += 0.10

    # Crowd support (max 0.25 at 5 supporters, non-negative)
    support = min(max(int(complaint.get("support_count") or 0), 0), 5)
    score += support * 0.05

    return round(min(score, 1.0), 2)

def determine_verification_status(score: float, ai_result: dict = None) -> str:
    """
    Rule-based verification status calculation.
    """
    if score >= 0.75:
        return "ACCEPTED"
    if score >= 0.40:
        return "NEEDS_REVIEW"
    return "PENDING"

def verify_complaint(complaint: dict, ai_result: dict = None) -> dict:
    """
    Runs full verification evaluation.
    Returns payload of fields to update on the complaint document.
    """
    score = compute_confidence_score(complaint)
    status = determine_verification_status(score, ai_result)

    return {
        "confidence_score": score,
        "verification_status": status,
        "verified_at": datetime.utcnow() if status == "ACCEPTED" else None,
    }
