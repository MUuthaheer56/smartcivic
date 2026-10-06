def estimate_severity(confidence: float, bbox_area: float, image_area: float, category: str, defect_count: int = 1) -> dict:
    """
    Computes a normalized visual severity score (0-10) and mapping level.
    """
    relative_area = bbox_area / image_area if image_area > 0 else 0.25
    
    # Category weights (Potholes weight higher than cracks)
    category_weights = {
        'pothole': 1.5,
        'alligator crack': 1.2,
        'longitudinal crack': 0.8,
        'transverse crack': 0.8,
        'garbage': 1.3,
        'sewage': 1.4,
        'water': 1.1,
        'other': 1.0
    }
    
    weight = category_weights.get(category.lower(), 1.0)
    
    # Core formula: confidence * relative_area * defect_count * weight
    raw_score = confidence * relative_area * defect_count * weight * 10
    
    # Cap at 10.0 and round to 1 decimal place
    severity_score = min(10.0, max(1.0, round(raw_score, 1)))
    
    # Severity levels
    if severity_score >= 7.0:
        level = "HIGH"
    elif severity_score >= 4.0:
        level = "MEDIUM"
    else:
        level = "LOW"
        
    return {
        "severity_score": severity_score,
        "severity_level": level
    }
