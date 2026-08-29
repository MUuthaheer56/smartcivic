"""
SmartCivic AI — Drain Blockage & Flood Risk Predictor
Formula: Risk = (complaint_count × avg_severity) × rain_probability × 10.0
Calls OpenWeatherMap free API for rain probability.
"""
import urllib.request
import json
from datetime import datetime, timedelta
from bson import ObjectId
from services.route_optimizer import haversine

DRAIN_PROXIMITY_KM = 0.05  # 50 metres
RISK_THRESHOLD = 60.0

# Known major drain/nala locations in Bengaluru (extend as needed)
KNOWN_DRAINS = [
    {"name": "Koramangala Nala", "lat": 12.9366, "lng": 77.6101},
    {"name": "Bellandur Lake Drain", "lat": 12.9253, "lng": 77.6761},
    {"name": "Hebbal Lake Drain", "lat": 13.0463, "lng": 77.5968},
    {"name": "Varthur Lake Drain", "lat": 12.9395, "lng": 77.7327},
    {"name": "KR Puram Drain", "lat": 13.0024, "lng": 77.7025},
]


def _get_rain_probability(lat: float, lng: float, api_key: str) -> float:
    """
    Fetch 48h rain probability from OpenWeatherMap One Call API.
    Returns float 0.0–1.0. Returns 0.5 as safe default on failure.
    """
    if not api_key:
        return 0.5  # Safe fallback when no API key configured
    
    url = (
        f"https://api.openweathermap.org/data/3.0/onecall"
        f"?lat={lat}&lon={lng}&exclude=current,minutely,daily,alerts"
        f"&appid={api_key}"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SmartCivic/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            # Take max pop (probability of precipitation) in next 48h
            hourly = data.get("hourly", [])[:48]
            if hourly:
                max_pop = max(h.get("pop", 0) for h in hourly)
                return float(max_pop)
    except Exception as e:
        print(f"[DrainPredictor] Weather API error: {e}")
    return 0.5


def compute_drain_risks(community_id: str, weather_api_key: str = "") -> list:
    """
    For each known drain near the community, compute flood risk score.
    
    Returns list of risk objects sorted by risk score descending.
    """
    from app import db
    from flask import current_app

    if not weather_api_key:
        weather_api_key = current_app.config.get("OPENWEATHER_API_KEY", "")

    cutoff = datetime.utcnow() - timedelta(days=7)
    garbage_issues = list(db.issues.find({
        "community_id": ObjectId(community_id),
        "category": {"$in": ["garbage", "sewage"]},
        "status": {"$ne": "rejected"},
        "created_at": {"$gte": cutoff}
    }, {"lat": 1, "lng": 1, "severity": 1}))

    results = []
    for drain in KNOWN_DRAINS:
        nearby = [
            iss for iss in garbage_issues
            if haversine(iss["lat"], iss["lng"], drain["lat"], drain["lng"]) <= DRAIN_PROXIMITY_KM
        ]
        if not nearby:
            continue

        complaint_count = len(nearby)
        avg_severity = sum(iss.get("severity", 3) for iss in nearby) / complaint_count
        rain_prob = _get_rain_probability(drain["lat"], drain["lng"], weather_api_key)

        risk_score = complaint_count * avg_severity * rain_prob * 10.0
        risk_score = round(min(100.0, risk_score), 2)

        results.append({
            "drain_name": drain["name"],
            "lat": drain["lat"],
            "lng": drain["lng"],
            "complaint_count": complaint_count,
            "avg_severity": round(avg_severity, 2),
            "rain_probability_48h": round(rain_prob, 3),
            "risk_score": risk_score,
            "alert": risk_score >= RISK_THRESHOLD,
            "computed_at": datetime.utcnow().isoformat()
        })

    return sorted(results, key=lambda x: x["risk_score"], reverse=True)
