import os
import requests
from datetime import datetime, timedelta
from pymongo import MongoClient

OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "dummy_key")  # free tier
DRAIN_RISK_THRESHOLD = 60  # tune this

def get_rain_probability(lat, lng):
    # If the key is dummy, return a simulated probability value to prevent API failure
    if OPENWEATHER_API_KEY == "dummy_key":
        # Deterministic simulation based on lat/lng to be testable
        return 0.82 if int(lat * 10) % 2 == 0 else 0.45
        
    url = f"https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lng}&appid={OPENWEATHER_API_KEY}&cnt=4"
    try:
        r = requests.get(url, timeout=5)
        if r.status_code != 200:
            return 0.5  # default if API fails
        forecasts = r.json().get("list", [])
        # average rain probability over next 48 hours
        probs = [f.get("pop", 0) for f in forecasts]
        return sum(probs) / len(probs) if probs else 0.5
    except Exception:
        return 0.5

def compute_drain_risk(db, drain_point):
    lat, lng = drain_point["lat"], drain_point["lng"]
    radius_m = 50
    radius_deg = radius_m / 111000

    # find garbage/waste complaints near the drain (last 7 days, excluding rejected/resolved)
    cutoff = datetime.utcnow() - timedelta(days=7)
    nearby = list(db.issues.find({
        "category": {"$in": ["waste management", "garbage", "drainage", "sewage"]},
        "status": {"$in": ["pending_validation", "validated", "assigned", "in_progress"]},
        "created_at": {"$gte": cutoff},
        "lat": {"$gte": lat - radius_deg, "$lte": lat + radius_deg},
        "lng": {"$gte": lng - radius_deg, "$lte": lng + radius_deg}
    }))

    if not nearby:
        # Return base rain probability hazard even if no complaints, or 0
        return 0

    count = len(nearby)
    avg_severity = sum(float(c.get("severity", 3.0)) for c in nearby) / count
    rain_prob = get_rain_probability(lat, lng)

    risk = (count * avg_severity) * rain_prob * 10.0
    return min(round(risk, 1), 100.0)

def run_drain_prediction(db):
    import json, pathlib
    drains_file = pathlib.Path(__file__).parent / "drain_locations.json"
    if not drains_file.exists():
        return []
        
    drains = json.loads(drains_file.read_text())
    alerts = []
    for drain in drains:
        score = compute_drain_risk(db, drain)
        drain["risk_score"] = score
        drain["rain_probability"] = get_rain_probability(drain["lat"], drain["lng"])
        # Fetch complaints count for detail metrics
        lat, lng = drain["lat"], drain["lng"]
        radius_deg = 50 / 111000
        cutoff = datetime.utcnow() - timedelta(days=7)
        complaints_count = db.issues.count_documents({
            "category": {"$in": ["waste management", "garbage", "drainage", "sewage"]},
            "status": {"$in": ["pending_validation", "validated", "assigned", "in_progress"]},
            "created_at": {"$gte": cutoff},
            "lat": {"$gte": lat - radius_deg, "$lte": lat + radius_deg},
            "lng": {"$gte": lng - radius_deg, "$lte": lng + radius_deg}
        })
        drain["nearby_complaint_count"] = complaints_count
        drain["computed_at"] = datetime.utcnow()
        
        db.drain_risk.update_one(
            {"drain_id": drain["id"]},
            {"$set": drain},
            upsert=True
        )
        if score > DRAIN_RISK_THRESHOLD:
            alerts.append(drain)
    return alerts
