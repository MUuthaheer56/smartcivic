"""
SmartCivic — Geolocation Utilities
Calculates Haversine distance in meters and validates geographic coordinates.
"""
import math

def validate_coordinates(lat: float, lng: float) -> bool:
    try:
        lat_f = float(lat)
        lng_f = float(lng)
        if not (-90.0 <= lat_f <= 90.0) or not (-180.0 <= lng_f <= 180.0):
            raise ValueError("Coordinates out of range")
        return True
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid coordinates: lat={lat}, lng={lng}. Error: {e}")

def haversine_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Returns distance in meters using Haversine formula."""
    validate_coordinates(lat1, lng1)
    validate_coordinates(lat2, lng2)
    
    R = 6371000.0 # Earth radius in meters
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    
    a = math.sin(dlat / 2.0) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c

def haversine(arg1, arg2, lat2=None, lng2=None) -> float:
    """
    Returns distance in km between two points.
    Supports either haversine((lat1, lng1), (lat2, lng2)) or haversine(lat1, lng1, lat2, lng2).
    """
    if isinstance(arg1, (tuple, list)) and isinstance(arg2, (tuple, list)):
        l1, g1 = arg1
        l2, g2 = arg2
    else:
        l1, g1, l2, g2 = float(arg1), float(arg2), float(lat2), float(lng2)
    return haversine_distance(l1, g1, l2, g2) / 1000.0

import logging
logger = logging.getLogger(__name__)

def calculate_haversine_distance(coord1: tuple, coord2: tuple) -> float:
    """
    Calculates straight-line distance (in kilometers) between two GPS points 
    (lat, lng) as a robust fallback when OSRM routing is unavailable.
    """
    try:
        lat1, lon1 = coord1
        lat2, lon2 = coord2
        
        R = 6371.0 # Earth radius in kilometers
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)

        a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))

        return round(R * c, 2)
    except Exception as e:
        logger.error(f"Haversine calculation error: {e}")
        return 0.0

def get_safe_route_details(origin: tuple, destination: tuple) -> dict:
    """
    Attempts to fetch route metrics; falls back gracefully to Haversine 
    estimation and standard urban speed metrics if external routing fails.
    """
    distance_km = calculate_haversine_distance(origin, destination)
    
    # Heuristic fallback: assume average municipal vehicle speed of 30 km/h
    estimated_minutes = max(int((distance_km / 30.0) * 60), 2)
    
    return {
        "distance_km": distance_km,
        "eta_minutes": estimated_minutes,
        "routing_provider": "haversine_fallback"
    }

