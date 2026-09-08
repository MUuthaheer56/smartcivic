"""
SmartCivic — Worker Management Service
Manages worker profiles, operational status, and task assignments.
"""
from app import db
from bson import ObjectId
from utils.geo_utils import haversine_distance

VALID_WORKER_STATUSES = {"available", "assigned", "working", "offline", "on_leave"}

def get_worker(worker_id: str) -> dict:
    try:
        w_obj = ObjectId(worker_id)
        worker = db.workers.find_one({"_id": w_obj}) or db.users.find_one({"_id": w_obj, "role": "worker"})
    except Exception:
        worker = None
    if not worker:
        raise ValueError(f"Worker not found for id '{worker_id}'")
    worker["worker_id"] = str(worker["_id"])
    return worker

def get_worker_tasks(worker_id: str, current_location: dict = None) -> list:
    get_worker(worker_id) # validates worker existence
    
    tasks = list(db.issues.find({
        "$or": [
            {"worker_id": ObjectId(worker_id)},
            {"assignment.worker_id": worker_id},
            {"assignment.worker_id": ObjectId(worker_id)}
        ],
        "status": {"$nin": ["closed", "rejected"]}
    }))
    
    formatted = []
    worker_lat = current_location.get("latitude") or current_location.get("lat") if current_location else None
    worker_lng = current_location.get("longitude") or current_location.get("lng") if current_location else None

    for t in tasks:
        loc = t.get("location", {})
        coords = loc.get("coordinates", [0, 0])
        t_lng, t_lat = coords[0], coords[1]
        
        dist = 0.0
        if worker_lat is not None and worker_lng is not None:
            dist = haversine_distance(float(worker_lat), float(worker_lng), float(t_lat), float(t_lng))
            
        images = t.get("images", [])
        img_url = images[0].get("url") if images else "/static/images/placeholder.jpg"
        
        formatted.append({
            "issue_id": str(t.get("issue_id") or t["_id"]),
            "description": t.get("description", ""),
            "priority": t.get("priority") or t.get("severity", "medium"),
            "image_url": img_url,
            "location": {
                "latitude": float(t_lat),
                "longitude": float(t_lng),
                "address": t.get("address", "")
            },
            "distance_meters": round(dist, 1),
            "status": t.get("status", "submitted"),
            "sla_deadline": t.get("sla_deadline").isoformat() if t.get("sla_deadline") else ""
        })
    return formatted

def update_worker_status(worker_id: str, new_status: str) -> dict:
    new_status = str(new_status).strip().lower()
    if new_status not in VALID_WORKER_STATUSES:
        raise ValueError(f"Invalid worker status '{new_status}'. Allowed: {VALID_WORKER_STATUSES}")
        
    try:
        w_obj = ObjectId(worker_id)
    except Exception:
        raise ValueError("Invalid worker ID format.")
        
    res = db.workers.update_one({"_id": w_obj}, {"$set": {"status": new_status, "is_available": (new_status == "available")}})
    if res.matched_count == 0:
        db.users.update_one({"_id": w_obj}, {"$set": {"status": new_status, "is_available": (new_status == "available")}})
        
    return get_worker(worker_id)
