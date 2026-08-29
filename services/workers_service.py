"""
SmartCivic — Workers Service
Handles querying nearest available workers and daily route scheduling/optimisation.
"""
import requests
import math
from datetime import datetime, timedelta
from bson import ObjectId
from flask import current_app
from ai.analytics import compute_worker_performance

DEPT_CATEGORY_MAP = {
    "Road Damage": "Roads",
    "Waste Management": "Sanitation",
    "Stray Animal": "Animal Control",
    "Noise": "Enforcement",
    "Footpath": "Roads",
    "Construction Hazard": "Roads",
    "Streetlight": "Electrical",
    "Drainage": "Drainage",
    "Lake Encroachment": "Environment",
    "Other": None,  # all departments
}


def get_nearest_available_worker(lat: float, lng: float, category: str, db) -> list:
    """
    Queries all AVAILABLE workers filtered by department matching the complaint category,
    then uses OSRM routing API to compute real road-distance travel times.
    Returns the top 3 workers sorted by ETA ascending.
    """
    dept = DEPT_CATEGORY_MAP.get(category)
    query = {"role": "field_worker", "status": "AVAILABLE"}
    if dept:
        query["department"] = dept
        
    workers = list(db.users.find(query, {"_id": 1, "name": 1, "phone": 1, "last_lat": 1, "last_lng": 1}))
    if not workers:
        return []
        
    osrm_base = current_app.config.get("OSRM_BASE", "http://router.project-osrm.org")
    results = []
    
    for w in workers:
        w_lat = w.get("last_lat")
        w_lng = w.get("last_lng")
        if w_lat is None or w_lng is None:
            continue
            
        try:
            url = f"{osrm_base}/route/v1/driving/{w_lng},{w_lat};{lng},{lat}?overview=false"
            resp = requests.get(url, timeout=3).json()
            route = resp["routes"][0]
            distance_m = route["distance"]
            duration_s = route["duration"]
            eta_min = round(duration_s / 60, 1)
        except Exception:
            # Fallback: Haversine straight-line
            R = 6371000
            phi1, phi2 = math.radians(lat), math.radians(w_lat)
            dphi = math.radians(w_lat - lat)
            dlam = math.radians(w_lng - lng)
            a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
            distance_m = 2 * R * math.atan2(math.sqrt(a), math.sqrt(1-a))
            eta_min = round(distance_m / (30 * 1000 / 60), 1)  # assume 30 km/h
            
        results.append({
            "worker_id": str(w["_id"]),
            "name": w.get("name"),
            "phone": w.get("phone", ""),
            "distance_m": round(distance_m, 0),
            "eta_min": eta_min
        })
        
    results.sort(key=lambda x: x["eta_min"])
    return results[:3]


def get_worker_daily_schedule(worker_id: str, date: datetime, db) -> list:
    """
    Builds an optimised daily route schedule for a worker using a nearest-neighbour TSP heuristic over OSRM distances.
    Returns complaints in the suggested visit order with estimated arrival times.
    """
    day_start = date.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = date.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    # Query assigned issues (complaints) that are in assigned/in_progress status
    complaints = list(db.issues.find({
        "assigned_to": ObjectId(worker_id),
        "status": {"$in": ["assigned", "in_progress"]}
    }, {"_id": 1, "address": 1, "lat": 1, "lng": 1, "category": 1, "severity": 1}))
    
    if not complaints:
        return []
        
    # Get worker's current location as start point
    worker = db.users.find_one({"_id": ObjectId(worker_id), "role": "field_worker"}, {"last_lat": 1, "last_lng": 1})
    current_lat = worker.get("last_lat", 12.9716) if worker else 12.9716  # fallback to Bangalore centre
    current_lng = worker.get("last_lng", 77.5946) if worker else 77.5946
    
    osrm_base = current_app.config.get("OSRM_BASE", "http://router.project-osrm.org")
    
    def travel_time(from_lat, from_lng, to_lat, to_lng) -> float:
        try:
            url = f"{osrm_base}/route/v1/driving/{from_lng},{from_lat};{to_lng},{to_lat}?overview=false"
            r = requests.get(url, timeout=2).json()
            return r["routes"][0]["duration"] / 60  # minutes
        except Exception:
            R = 6371000
            phi1, phi2 = math.radians(from_lat), math.radians(to_lat)
            dphi = math.radians(to_lat - from_lat)
            dlam = math.radians(to_lng - from_lng)
            a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
            d = 2 * R * math.atan2(math.sqrt(a), math.sqrt(1-a))
            return d / (30000 / 60)  # 30 km/h in m/min
            
    # Nearest-neighbour TSP heuristic
    unvisited = list(complaints)
    ordered = []
    clat, clng = current_lat, current_lng
    current_time = datetime.utcnow().replace(second=0, microsecond=0)
    
    while unvisited:
        best, best_t = None, float("inf")
        for c in unvisited:
            t = travel_time(clat, clng, c.get("lat", 0), c.get("lng", 0))
            if t < best_t:
                best_t, best = t, c
                
        current_time += timedelta(minutes=best_t + 30)  # 30min avg job time
        
        ordered.append({
            "sequence": len(ordered) + 1,
            "complaint_id": str(best["_id"]),
            "address": best.get("address", ""),
            "lat": best.get("lat"),
            "lng": best.get("lng"),
            "category": best.get("category", ""),
            "priority": "HIGH" if best.get("severity", 1) >= 4 else "NORMAL",
            "estimated_arrival": current_time.strftime("%H:%M"),
            "travel_minutes": round(best_t, 1),
        })
        
        clat, clng = best.get("lat", clat), best.get("lng", clng)
        unvisited.remove(best)
        
    return ordered
