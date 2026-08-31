"""
SmartCivic+ — Route Optimization Service
Consolidates all route/map utilities. Connects to OSRM with local Haversine fallback.
"""
import requests
import math
from flask import current_app

def haversine(coord1: tuple, coord2: tuple) -> float:
    """
    Returns straight-line distance in km between two (lat, lng) tuples.
    """
    lat1, lon1 = coord1
    lat2, lon2 = coord2
    R = 6371.0 # Earth radius in km
    
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def get_route(origin_coords: tuple, destination_coords: tuple) -> dict:
    """
    Returns actual road route using OSRM.
    origin_coords: (lat, lng), destination_coords: (lat, lng)
    """
    lat1, lon1 = origin_coords
    lat2, lon2 = destination_coords
    
    osrm_base = current_app.config.get("OSRM_BASE", "http://router.project-osrm.org") if current_app else "http://router.project-osrm.org"
    url = f"{osrm_base}/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?geometries=geojson&overview=full"
    
    try:
        r = requests.get(url, timeout=3)
        if r.status_code == 200:
            data = r.json()
            if data.get("code") == "Ok" and data.get("routes"):
                route = data["routes"][0]
                distance_km = round(route["distance"] / 1000.0, 3)
                duration_minutes = round(route["duration"] / 60.0, 1)
                
                # OSRM coordinates are in [lng, lat] format, convert to [lat, lng] for frontend Leaflet compatibility
                geom = route.get("geometry", {})
                waypoints = [[coords[1], coords[0]] for coords in geom.get("coordinates", [])]
                
                return {
                    "distance_km": distance_km,
                    "duration_minutes": duration_minutes,
                    "polyline": waypoints
                }
    except Exception as e:
        print(f"[Route Service] OSRM route request failed: {e}. Falling back to Haversine.")
        
    # Haversine straight-line fallback
    dist = haversine(origin_coords, destination_coords)
    duration = round(dist / (30.0 / 60.0), 1) # assume 30 km/h
    return {
        "distance_km": round(dist, 3),
        "duration_minutes": duration,
        "polyline": [[lat1, lon1], [lat2, lon2]]
    }

def optimize_multi_stop_route(worker_location: tuple, issue_locations: list) -> list:
    """
    Solves multi-stop route optimization using nearest-neighbor heuristic.
    issue_locations: list of dicts -> {"issue_id": str, "coords": (lat, lng)}
    Returns: list of dicts containing ordered stops and the segment route routes.
    """
    unvisited = list(issue_locations)
    current_loc = worker_location
    ordered_route = []
    
    while unvisited:
        nearest_idx = 0
        min_dist = float("inf")
        
        for idx, item in enumerate(unvisited):
            dist = haversine(current_loc, item["coords"])
            if dist < min_dist:
                min_dist = dist
                nearest_idx = idx
                
        next_stop = unvisited.pop(nearest_idx)
        route_segment = get_route(current_loc, next_stop["coords"])
        
        ordered_route.append({
            "issue_id": next_stop["issue_id"],
            "coords": next_stop["coords"],
            "distance_km": route_segment["distance_km"],
            "duration_minutes": route_segment["duration_minutes"],
            "polyline": route_segment["polyline"]
        })
        
        current_loc = next_stop["coords"]
        
    return ordered_route
