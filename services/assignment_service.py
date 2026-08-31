"""
SmartCivic+ — Worker Recommendation & Assignment Service
"""
from datetime import datetime
from bson import ObjectId
from app import db
from models.assignment import create_assignment_doc
from services.route_service import haversine, get_route
from services.complaint_service import update_status
from services.notification_service import send, COMPLAINT_ASSIGNED
from services.audit_service import log_audit

SKILL_MAPPINGS = {
    "road": ["road_repair", "roads", "road"],
    "water": ["water_supply", "water"],
    "electricity": ["electrical", "electricity"],
    "sanitation": ["sanitation"],
    "drainage": ["drainage"],
    "other": []
}

def recommend_workers(issue: dict, limit=5) -> list:
    """
    Finds and scores available field workers matching the required category skills and capacity.
    """
    category = issue.get("category", "other").lower()
    required_skills = SKILL_MAPPINGS.get(category, [])
    
    # Coordinates of issue
    issue_coords = issue.get("location", {}).get("coordinates", [0.0, 0.0])
    issue_lat, issue_lng = issue_coords[1], issue_coords[0]
    
    # Query available workers who have less than 5 active assignments
    query = {
        "role": "worker",
        "is_available": True,
        "active_assignments": {"$lt": 5}
    }
    
    workers = list(db.users.find(query))
    recommendations = []
    
    for w in workers:
        skills = [s.lower() for s in w.get("skills", [])]
        # Check skill match (if skills are defined, must overlap or be empty for fallback)
        if required_skills and not any(s in skills for s in required_skills):
            continue
            
        w_coords = w.get("current_location", {}).get("coordinates", [0.0, 0.0])
        w_lat, w_lng = w_coords[1], w_coords[0]
        
        # Calculate distance
        dist = haversine((w_lat, w_lng), (issue_lat, issue_lng))
        
        # Distance score (max 50 points, 10km range)
        dist_score = max(0.0, 1.0 - (dist / 10.0)) * 50.0
        
        # Load score (max 30 points, fewer active assignments = higher score)
        active_jobs = w.get("active_assignments", 0)
        load_score = ((5.0 - active_jobs) / 5.0) * 30.0
        
        # SLA compatibility check (max 20 points, if they can travel and resolve before deadline)
        sla_compatible = True
        deadline = issue.get("sla_deadline")
        if deadline:
            if isinstance(deadline, str):
                deadline = datetime.fromisoformat(deadline.replace("Z", "+00:00")).replace(tzinfo=None)
            time_remaining_hours = (deadline - datetime.utcnow()).total_seconds() / 3600.0
            
            # Assume 30 km/h travel time + 1 hour average job time
            eta_hours = (dist / 30.0) + 1.0
            if eta_hours > time_remaining_hours:
                sla_compatible = False
                
        sla_score = 20.0 if sla_compatible else 0.0
        total_score = dist_score + load_score + sla_score
        
        eta_min = round((dist / 30.0) * 60.0, 1)
        
        recommendations.append({
            "worker": {
                "id": str(w["_id"]),
                "name": w.get("name"),
                "email": w.get("email"),
                "active_assignments": active_jobs,
                "skills": w.get("skills"),
                "average_rating": w.get("average_rating", 0.0),
                "total_ratings": w.get("total_ratings", 0)
            },
            "score": round(total_score, 1),
            "distance_km": round(dist, 2),
            "eta_minutes": eta_min,
            "sla_compatible": sla_compatible
        })
        
    # Sort recommendations by score descending
    recommendations.sort(key=lambda x: x["score"], reverse=True)
    return recommendations[:limit]

def assign_worker(issue_id, worker_id, officer_id) -> dict:
    """
    Binds a worker to a complaint, updating active loads, and logging audit paths.
    """
    issue = db.issues.find_one({"_id": ObjectId(issue_id)})
    if not issue:
        raise ValueError("Issue not found")
        
    worker = db.users.find_one({"_id": ObjectId(worker_id), "role": "worker"})
    if not worker:
        raise ValueError("Worker not found")
        
    # 1. Create Assignment document
    assign_doc = create_assignment_doc(issue_id, worker_id, officer_id)
    db.assignments.insert_one(assign_doc)
    
    # 2. Update issue worker ref and change status using complaint_service
    db.issues.update_one(
        {"_id": ObjectId(issue_id)},
        {"$set": {
            "worker_id": ObjectId(worker_id),
            "officer_id": ObjectId(officer_id)
        }}
    )
    update_status(issue_id, "assigned", officer_id, reason=f"Assigned to worker {worker.get('name')}.")
    
    # 3. Increment worker active load count
    new_jobs = worker.get("active_assignments", 0) + 1
    availability = new_jobs < 5
    db.users.update_one(
        {"_id": ObjectId(worker_id)},
        {"$set": {
            "active_assignments": new_jobs,
            "is_available": availability
        }}
    )
    
    # 4. Log audit & send notifications
    log_audit("user", worker_id, officer_id, "JOB_ASSIGNED", reason=f"Assigned issue {issue_id}.")
    send(COMPLAINT_ASSIGNED, str(worker_id), str(issue_id))
    
    return assign_doc
