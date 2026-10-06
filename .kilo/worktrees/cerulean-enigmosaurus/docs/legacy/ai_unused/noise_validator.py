"""
SmartCivic AI — Noise Level Validator
Receives dB SPL reading from browser Web Audio API and validates against
CPCB (Central Pollution Control Board) noise limits for India.
"""

# CPCB Noise Standards (dB SPL) — India
CPCB_LIMITS = {
    "residential": {"day": 55, "night": 45},
    "commercial":  {"day": 65, "night": 55},
    "industrial":  {"day": 75, "night": 70},
    "silence":     {"day": 50, "night": 40}   # hospital/school zones
}

SEVERITY_BANDS = [
    (0, 5,  1),   # 0-5 dB above limit → severity 1
    (5, 10, 2),   # 5-10 → severity 2
    (10, 15, 3),  # 10-15 → severity 3
    (15, 25, 4),  # 15-25 → severity 4
    (25, 999, 5)  # >25 → severity 5
]


def validate_noise(db_spl: float, zone_type: str = "residential", is_night: bool = False) -> dict:
    """
    Validate a dB SPL reading against CPCB zone limits.
    
    Args:
        db_spl: Measured decibel Sound Pressure Level
        zone_type: "residential" | "commercial" | "industrial" | "silence"
        is_night: True if measurement taken between 22:00–06:00
    
    Returns:
        {
            "compliant": bool,
            "measured_db": float,
            "limit_db": int,
            "excess_db": float,
            "zone": str,
            "period": str,
            "estimated_severity": int,
            "cpcb_status": str
        }
    """
    period = "night" if is_night else "day"
    limits = CPCB_LIMITS.get(zone_type, CPCB_LIMITS["residential"])
    limit = limits[period]
    excess = round(db_spl - limit, 1)
    compliant = excess <= 0

    severity = 1
    if not compliant:
        for low, high, sev in SEVERITY_BANDS:
            if low <= excess < high:
                severity = sev
                break

    if compliant:
        status = "COMPLIANT"
    elif excess <= 5:
        status = "MARGINALLY EXCEEDED"
    elif excess <= 15:
        status = "SIGNIFICANTLY EXCEEDED"
    else:
        status = "CRITICALLY EXCEEDED"

    return {
        "compliant": compliant,
        "measured_db": round(db_spl, 1),
        "limit_db": limit,
        "excess_db": max(0.0, excess),
        "zone": zone_type,
        "period": period,
        "estimated_severity": severity,
        "cpcb_status": status
    }
