"""
SmartCivic — AI Confidence Scoring & Decision Explainer
"""

def score_pipeline_confidence(ai_result: dict) -> dict:
    """
    Aggregates raw scores from every detector stage into a single 0-100 composite confidence integer.
    band: "HIGH" >=75, "MEDIUM" 45-74, "LOW" <45
    """
    scores = {}
    
    # YOLO detection confidence (0-1 -> 0-40 pts)
    yolo_conf = ai_result.get("ai_confidence", 0) or 0
    scores["yolo_detection"] = round(float(yolo_conf) * 40, 1)
    
    # Image quality (passed=10, failed=0)
    quality = ai_result.get("quality", {})
    scores["image_quality"] = 10 if quality.get("passed") else 0
    
    # Duplicate check (not duplicate = 20, is duplicate = 0)
    scores["uniqueness"] = 0 if ai_result.get("is_duplicate") else 20
    
    # Specialised module hits (each confirmed hit adds up to 30 pts total)
    spec = ai_result.get("specialised", {})
    spec_score = 0
    if spec.get("streetlight", {}).get("is_dark"): 
        spec_score += 5
    if spec.get("footpath", {}).get("impact") == "HIGH": 
        spec_score += 5
    if spec.get("dump_age", {}).get("estimated_days", 0) > 3: 
        spec_score += 5
    if spec.get("noise", {}).get("violation"): 
        spec_score += 5
    if spec.get("lakes", {}).get("in_buffer"): 
        spec_score += 5
    if spec.get("animals", {}).get("detected"): 
        spec_score += 5
    if spec.get("construction", {}).get("hazard"): 
        spec_score += 5
        
    scores["specialised_modules"] = min(spec_score, 30)
    total = sum(scores.values())
    band = "HIGH" if total >= 75 else "MEDIUM" if total >= 45 else "LOW"
    
    return {
        "confidence": int(min(total, 100)),
        "breakdown": scores,
        "band": band
    }


def explain_ai_decision(ai_result: dict, db=None) -> str:
    """
    Returns a 2-4 sentence human-readable summary of the AI analysis.
    """
    parts = []
    
    # Detection
    detected_class = ai_result.get("ai_detected_class") or ai_result.get("category", "issue")
    conf = ai_result.get("ai_confidence", 0)
    if conf:
        pct = int(float(conf) * 100)
        parts.append(f"The image analysis detected a {detected_class.replace('_', ' ')} with {pct}% confidence.")
    else:
        parts.append(f"The complaint was categorised as: {detected_class.replace('_', ' ')}.")
        
    # Severity
    sev = ai_result.get("severity_score")
    if sev is not None:
        level = "HIGH" if sev > 0.7 else "MEDIUM" if sev > 0.4 else "LOW"
        parts.append(f"Severity was assessed as {level} (score: {round(float(sev), 2)}).")
        
    # Special flags
    spec = ai_result.get("specialised", {})
    if spec.get("lakes", {}).get("in_buffer"):
        parts.append("⚠ This location falls within a protected lake buffer zone — the complaint has been given CRITICAL priority.")
    if spec.get("footpath", {}).get("impact") == "HIGH":
        parts.append("A school or clinic is located within 50m, escalating the impact level.")
        
    if ai_result.get("is_duplicate"):
        dup_of = ai_result.get("duplicate_of", "another report")
        parts.append(f"This submission appears to be a duplicate of complaint {dup_of}.")
        
    # Routing decision
    routing = ai_result.get("routing_status", "")
    if routing == "AUTO":
        parts.append("Based on high confidence, this complaint was automatically verified and queued for worker assignment.")
    elif routing == "ADMIN_REVIEW":
        parts.append("Confidence was below the auto-route threshold; an admin will review this complaint before assignment.")
        
    return " ".join(parts)
