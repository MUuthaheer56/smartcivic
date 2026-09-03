def route_confidence_threshold(confidence: float) -> dict:
    """
    Route complaint validation path based on AI confidence.
    """
    if confidence >= 0.85:
        routing = "AUTO"
    elif confidence >= 0.60:
        routing = "COMMUNITY_VERIFY"
    else:
        routing = "ADMIN_REVIEW"
        
    return {
        "routing": routing,
        "threshold_used": 0.60
    }
