"""
SmartCivic — Road Network Routing Service
Integrates with OSRM road geometry engine for real road-network navigation.
Strictly avoids straight-line geometry when routing service is unavailable.
"""
import requests
from config import Config
from utils.geo_utils import validate_coordinates, haversine_distance

def calculate_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    return haversine_distance(lat1, lng1, lat2, lng2)

def calculate_eta(distance_meters: float, mode: str = "driving") -> int:
    speeds_m_s = {
        "driving": 8.33, # ~30 km/h urban
        "biking": 4.16,  # ~15 km/h
        "walking": 1.38   # ~5 km/h
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
    
    # Query OSRM engine
    url = f"{Config.ROUTING_ENGINE_URL}{orig_lng},{orig_lat};{dest_lng},{dest_lat}?overview=full&geometries=geojson"
    try:
        resp = requests.get(url, timeout=Config.ROUTING_TIMEOUT_SECONDS)
        if resp.status_code == 200:
            data = resp.json()
            routes = data.get("routes", [])
            if routes:
                route = routes[0]
                coords_lng_lat = route.get("geometry", {}).get("coordinates", [])
                # Convert GeoJSON [lng, lat] to [lat, lng]
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
    except Exception as e:
        return {
            "available": False,
            "reason": "routing_service_unavailable"
        }
