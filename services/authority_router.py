"""
SmartCivic v2 — Authority Router & Priority Rules Engine
Maps issues to responsible municipal authorities and computes priority scores.
"""
import re
from app import db

PRIORITY_RULES = {
    ("medical_emergency", "critical"): "P0",
    ("fire_emergency",    "critical"): "P0",
    ("crime_safety",      "critical"): "P0",
    ("gas_environment",   "critical"): "P0",
    ("electricity",       "critical"): "P0",   # live wire
    ("water",             "critical"): "P1",
    ("flooding",          "critical"): "P1",
    ("roads",             "critical"): "P1",
    ("trees",             "critical"): "P1",
    ("water",             "high"):     "P2",
    ("electricity",       "high"):     "P2",
    ("roads",             "high"):     "P2",
    ("flooding",          "high"):     "P2",
    ("trees",             "high"):     "P2",
    ("solid_waste",       "high"):     "P2",
    ("public_health",     "high"):     "P2",
    ("traffic",           "high"):     "P1",
}

DEFAULT_SERVICE_AUTHORITIES = {
    "water": "BWSSB",
    "electricity": "BESCOM",
    "traffic": "BTP",
    "transport": "BMTC",
    "food_safety": "FSSAI",
    "medical_emergency": "ERSS-112",
    "fire_emergency": "ERSS-112",
    "crime_safety": "ERSS-112",
    "gas_environment": "ERSS-112",
    "roads": "GBA-CORP-ROADS",
    "solid_waste": "GBA-CORP-SWM",
    "sanitation": "GBA-CORP-SWM",
    "flooding": "KSNDMC",
    "drainage": "GBA-CORP-SWD",
    "trees": "GBA-CORP-TREES",
    "illegal_construction": "GBA-CORP-TP"
}

def compute_priority(service: str, severity: str, emergency: bool = False) -> str:
    """Calculates P0, P1, P2, P3 priority level."""
    if emergency:
        return "P0"
    svc = (service or "roads").lower()
    sev = (severity or "medium").lower()
    return PRIORITY_RULES.get((svc, sev), "P2" if sev in ["high", "critical"] else "P3")

def resolve_authority(service: str, issue_type: str = "", ward_id: str = None) -> dict:
    """
    Queries authority_registry MongoDB collection for responsible municipal authority.
    Falls back to deterministic dictionary if DB lookup is empty or unavailable.
    """
    svc = (service or "roads").lower()
    
    try:
        candidates = list(db.authority_registry.find(
            {"service_types": {"$in": [svc]}, "active": True},
            {"_id": 0}
        ))
    except Exception:
        candidates = []

    if candidates:
        primary = candidates[0]
        sub_dept = primary.get("sub_departments", {}).get(svc)
        authority_id = sub_dept or primary.get("authority_id", "GBA-CORP")
        secondary = [c["authority_id"] for c in candidates[1:] if c.get("authority_id") != authority_id]
        return {
            "authority_id": authority_id,
            "authority_name": primary.get("authority_name", "Municipal Authority"),
            "phone": primary.get("phone"),
            "secondary": secondary,
            "bypass_queue": primary.get("bypass_queue", False),
            "routing_confidence": "high" if ward_id else "medium"
        }

    # Deterministic fallback
    auth_id = DEFAULT_SERVICE_AUTHORITIES.get(svc, "GBA-CORP")
    return {
        "authority_id": auth_id,
        "authority_name": "City Municipal Corporation / Authority",
        "phone": "1533",
        "secondary": [],
        "bypass_queue": svc in ["medical_emergency", "fire_emergency", "crime_safety"],
        "routing_confidence": "medium"
    }

def extract_location_hints(text: str) -> list:
    """Extracts landmark and street hints from text."""
    if not text:
        return []
    LOCATION_PATTERNS = [
        r'near\s+([\w\s]+?)(?:\.|,|$)',
        r'opposite\s+([\w\s]+?)(?:\.|,|$)',
        r'at\s+([\w\s]+(?:junction|circle|signal|gate|stop|road|layout|nagar|puram|cross))',
        r'([\w\s]+(?:metro|bus stop|junction|main road|cross))',
    ]
    hints = []
    text_lower = text.lower()
    for pattern in LOCATION_PATTERNS:
        found = re.findall(pattern, text_lower)
        hints.extend([f.strip() for f in found if len(f.strip()) > 3])
    return list(set(hints))

import requests
from config import Config
from utils.geo_utils import validate_coordinates, haversine_distance

def calculate_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    return haversine_distance(lat1, lng1, lat2, lng2)

def calculate_eta(distance_meters: float, mode: str = "driving") -> int:
    speeds_m_s = {
        "driving": 8.33,
        "biking": 4.16,
        "walking": 1.38
    }
    speed = speeds_m_s.get(mode, 8.33)
    return int(distance_meters / speed) if speed > 0 else 0

def get_route(origin: dict, destination: dict) -> dict:
    orig_lat = origin.get("lat") if "lat" in origin else origin.get("latitude")
    orig_lng = origin.get("lng") if "lng" in origin else origin.get("longitude")
    dest_lat = destination.get("lat") if "lat" in destination else destination.get("latitude")
    dest_lng = destination.get("lng") if "lng" in destination else destination.get("longitude")
    
    validate_coordinates(orig_lat, orig_lng)
    validate_coordinates(dest_lat, dest_lng)
    
    url = f"{Config.ROUTING_ENGINE_URL}{orig_lng},{orig_lat};{dest_lng},{dest_lat}?overview=full&geometries=geojson"
    try:
        resp = requests.get(url, timeout=Config.ROUTING_TIMEOUT_SECONDS)
        if resp.status_code == 200:
            data = resp.json()
            routes = data.get("routes", [])
            if routes:
                route = routes[0]
                coords_lng_lat = route.get("geometry", {}).get("coordinates", [])
                geometry = [[pt[1], pt[0]] for pt in coords_lng_lat]
                return {
                    "available": True,
                    "distance_meters": int(route.get("distance", 0)),
                    "duration_seconds": int(route.get("duration", 0)),
                    "geometry": geometry
                }
        return {
            "available": False,
            "reason": "no_route_found"
        }
    except Exception:
        return {
            "available": False,
            "reason": "routing_service_unavailable"
        }

