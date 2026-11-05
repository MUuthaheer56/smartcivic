"""
SmartCivic - Defect Severity Rubric (Provisional)
Maps detected defect classes (RDD2022) and bounding-box area ratios to severity tiers.

NOTICE (Rule R10 Compliance):
This is a written provisional severity rubric derived from bounding box geometry and damage taxonomy.
It is NOT yet validated by municipal field officers against real-world road repairs.
Do not represent these scores as empirically validated defect severity until an officer-panel
validation study has been conducted.
"""
from typing import Tuple, Dict, Any

# RDD2022 Defect Classes
DEFECT_CLASSES = {
    "D00": "longitudinal_crack",
    "D10": "transverse_crack",
    "D20": "alligator_crack",
    "D40": "pothole",
    "D43": "crosswalk_blur",
    "D44": "white_line_blur"
}

# Provisional classification thresholds based on bounding box area ratio (bbox_area / image_area)
# Format: (min_area_ratio, severity_level, base_score)
PROVISIONAL_RUBRIC: Dict[str, list] = {
    # Potholes pose immediate vehicle suspension and two-wheeler rollover hazards
    "D40": [
        (0.10, "critical", 0.95),  # Large pothole covering >=10% of field of view
        (0.03, "high",     0.75),  # Medium pothole (3%-10%)
        (0.00, "medium",   0.50),  # Minor pothole (<3%)
    ],
    # Alligator cracks indicate base-course structural failure
    "D20": [
        (0.15, "high",     0.75),  # Extensive alligator cracking pattern
        (0.05, "medium",   0.55),  # Moderate fatigue cracking
        (0.00, "low",      0.30),  # Early surface fatigue
    ],
    # Longitudinal cracks along wheelpaths
    "D00": [
        (0.20, "medium",   0.50),  # Long longitudinal crack across span
        (0.00, "low",      0.25),  # Minor longitudinal surface crack
    ],
    # Transverse cracks across pavement width
    "D10": [
        (0.20, "medium",   0.50),  # Severe transverse joint reflection
        (0.00, "low",      0.25),  # Minor thermal transverse crack
    ],
    # Road markings
    "D43": [
        (0.00, "low",      0.20),
    ],
    "D44": [
        (0.00, "low",      0.20),
    ]
}


def calculate_defect_severity(defect_code: str, area_ratio: float = 0.0) -> Tuple[str, float]:
    """
    Computes provisional severity tier and normalized severity score [0.0, 1.0]
    based on defect class and area ratio.
    Returns (severity_tier, numeric_score).
    """
    code = (defect_code or "").upper().strip()
    rules = PROVISIONAL_RUBRIC.get(code)
    
    if not rules:
        # Unknown defect fallback
        return "medium", 0.40

    area = max(0.0, float(area_ratio or 0.0))
    for min_area, sev, score in rules:
        if area >= min_area:
            return sev, score

    return "low", 0.20

