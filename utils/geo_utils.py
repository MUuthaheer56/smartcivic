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
