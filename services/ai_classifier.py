"""
SmartCivic v2 — AI Classification Service
Combines Gemini LLM text classification with deterministic emergency regex safety triggers.
"""
import json
import re
from services.ai_service import analyze_text as call_gemini_ai

SERVICE_CLASSES = [
    "water", "electricity", "roads", "flooding", "trees",
    "solid_waste", "public_health", "animals", "traffic",
    "illegal_construction", "parks_lakes", "transport",
    "general_civic", "gas_environment", "medical_emergency",
    "fire_emergency", "crime_safety", "multi_issue", "unknown_other",
    "food_safety", "road"
]

EMERGENCY_PATTERNS = [
    (r'\bfire\b',           r'\b(no|out|old|was|yesterday|extinguished)\b'),
    (r'\baccident\b',       r'\bno accident\b|\baccident.{0,20}(ago|yesterday)\b'),
    (r'\bunconscious\b',    None),
    (r'\bnot breathing\b',  None),
    (r'\bgas leak\b',       r'\bno gas leak\b'),
    (r'\btrapped\b',        r'\b(not|no longer) trapped\b'),
    (r'\bbleeding\b',       r'\b(minor|small|no) bleeding\b'),
    (r'\bdying\b',          None),
    (r'\bhelp me\b',        None),
    (r'\blive wire\b',      r'\bno live wire\b'),
    (r'\belectric shock\b', None),
    (r'\bbeesi\b',          None),
    (r'\bagni\b',           None),
]

def pattern_emergency_check(text: str) -> bool:
    """Deterministic regex pattern matcher with negation filtering."""
    if not text:
        return False
    text_lower = text.lower()
    for pattern, negation in EMERGENCY_PATTERNS:
        if re.search(pattern, text_lower):
            if negation and re.search(negation, text_lower):
                continue
            return True
    return False

def _compute_route(pred: dict) -> str:
    """Computes high-level AI route decision."""
    emg_state = pred.get("emergency_state")
    if emg_state in ("IMMEDIATE_112", "SAFETY_REVIEW"):
        return emg_state

    svc = pred.get("service", "unknown_other")
    conf = float(pred.get("confidence", 0.0))

    if svc == "unknown_other":
        return "HUMAN_TRIAGE"
    if pred.get("needs_clarification"):
        return "CLARIFICATION_NEEDED"
    if conf >= 0.90:
        return "AUTO_ROUTE"
    if conf >= 0.70:
        return "OFFICER_CONFIRM"
    return "GEMINI_FALLBACK"

def classify_complaint(text: str) -> dict:
    """
    Main classification pipeline entry point.
    Returns structured JSON containing service, issue_type, severity, emergency_state, route_decision.
    """
    if not text:
        text = "Civic complaint"

    # Call core Gemini AI service
    ai_raw = call_gemini_ai(text)
    
    cat = ai_raw.get("category", "other")
    if cat == "road":
        service = "roads"
    elif cat in SERVICE_CLASSES:
        service = cat
    else:
        service = "roads" if cat in ["road", "pothole"] else "unknown_other"

    confidence = float(ai_raw.get("confidence", 0.85))
    severity = ai_raw.get("severity", "medium")

    result = {
        "service": service,
        "issue_type": ai_raw.get("type", "general_issue"),
        "severity": severity,
        "urgency": "immediate" if severity == "critical" else "standard",
        "emergency": ai_raw.get("is_emergency", False) or (severity == "critical"),
        "needs_clarification": confidence < 0.60,
        "is_multi_issue": " and " in text.lower() or "," in text,
        "confidence": confidence,
    }

    # Safety override check
    has_emergency_pattern = pattern_emergency_check(text)
    if has_emergency_pattern:
        if not result.get("emergency") and confidence < 0.85:
            result["emergency_state"] = "SAFETY_REVIEW"
        else:
            result["emergency"] = True
            result["emergency_state"] = "IMMEDIATE_112"
    else:
        if result.get("emergency"):
            result["emergency_state"] = "IMMEDIATE_112"
        else:
            result["emergency_state"] = None

    result["route_decision"] = _compute_route(result)
    return result
