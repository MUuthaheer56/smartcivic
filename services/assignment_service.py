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
    Binds a worker to a complaint, updating active loads, worker status, and logging audit paths.
    """
    try:
        issue_obj_id = ObjectId(issue_id) if ObjectId.is_valid(issue_id) else None
        issue = db.issues.find_one({"_id": issue_obj_id}) if issue_obj_id else db.issues.find_one({"issue_id": issue_id})
    except Exception:
        issue = None
        
    if not issue:
        raise ValueError("Issue not found")
        
    w_obj_id = ObjectId(worker_id) if ObjectId.is_valid(worker_id) else None
    worker = db.users.find_one({"_id": w_obj_id}) if w_obj_id else db.users.find_one({"user_id": worker_id})
    worker_prof = db.workers.find_one({"_id": w_obj_id}) if w_obj_id else db.workers.find_one({"user_id": worker_id})
    
    if not worker and not worker_prof:
        raise ValueError("Worker not found")
        
    # Availability Check
    w_status = (worker_prof.get("status") if worker_prof else None) or (worker.get("status") if worker else None) or "available"
    w_avail = (worker.get("is_available", True) if worker else True)
    if w_status == "assigned" or w_avail is False:
        raise ValueError("Worker is not available for assignment.")
        
    now = datetime.utcnow()
    assignment_entry = {
        "worker_id": str(worker_id),
        "assigned_at": now.isoformat(),
        "assigned_by": str(officer_id)
    }
    
    # 1. Create Assignment document
    assign_doc = create_assignment_doc(str(issue["_id"]), str(worker_id), str(officer_id))
    db.assignments.insert_one(assign_doc)
    
    # 2. Update issue worker ref, assignment dict, assignment_history, and status
    db.issues.update_one(
        {"_id": issue["_id"]},
        {"$set": {
            "worker_id": ObjectId(worker_id) if ObjectId.is_valid(worker_id) else worker_id,
            "officer_id": ObjectId(officer_id) if ObjectId.is_valid(officer_id) else officer_id,
            "assignment": assignment_entry
        }, "$push": {
            "assignment_history": assignment_entry
        }}
    )
    update_status(str(issue["_id"]), "assigned", officer_id, reason=f"Assigned to worker {worker.get('name') if worker else 'Worker'}.")
    
    # 3. Update worker status and active load
    if worker:
        new_jobs = worker.get("active_assignments", 0) + 1
        db.users.update_one(
            {"_id": worker["_id"]},
            {"$set": {
                "active_assignments": new_jobs,
                "is_available": False,
                "status": "assigned"
            }}
        )
    if worker_prof:
        db.workers.update_one(
            {"_id": worker_prof["_id"]},
            {"$set": {
                "status": "assigned"
            }}
        )
        
    # 4. Log audit & send notifications
    log_audit("user", worker_id, officer_id, "JOB_ASSIGNED", reason=f"Assigned issue {issue_id}.")
    send(COMPLAINT_ASSIGNED, str(worker_id), str(issue_id))
    return db.issues.find_one({"_id": issue["_id"]})
    
def get_required_worker_skills(issue: dict) -> list:
    category = issue.get("category", "other").lower()
    issue_type = issue.get("type") or issue.get("issue_type", "")
    from config import Config
    skills = Config.ISSUE_TYPE_TO_SKILLS.get(issue_type, SKILL_MAPPINGS.get(category, []))
    return skills

def find_matching_workers(issue: dict) -> list:
    required_skills = get_required_worker_skills(issue)
    query = {
        "$or": [{"role": "worker"}, {"status": "available"}],
        "is_available": True
    }
    workers = list(db.users.find(query)) + list(db.workers.find({"status": "available"}))
    matched = []
    seen = set()
    for w in workers:
        w_id = str(w["_id"])
        if w_id in seen:
            continue
        seen.add(w_id)
        w_skills = [s.lower() for s in w.get("skills", [])]
        if not required_skills or any(s in w_skills for s in required_skills):
            matched.append(w)
    return rank_workers(matched, issue)

def rank_workers(workers: list, issue: dict) -> list:
    issue_coords = issue.get("location", {}).get("coordinates", [0.0, 0.0])
    issue_lat, issue_lng = issue_coords[1], issue_coords[0]
    
    scored = []
    for w in workers:
        w_coords = w.get("current_location", {}).get("coordinates") or w.get("location", {}).get("coordinates", [0.0, 0.0])
        w_lat, w_lng = w_coords[1], w_coords[0]
        dist = haversine((w_lat, w_lng), (issue_lat, issue_lng))
        jobs = w.get("active_assignments", 0)
        score = (100.0 - min(100.0, dist * 5.0)) + ((5.0 - jobs) * 10.0)
        scored.append((score, dist, w))
        
    scored.sort(key=lambda x: x[0], reverse=True)
    return [item[2] for item in scored]

def unassign_worker(issue_id: str, officer_id: str) -> dict:
    issue = db.issues.find_one({"_id": ObjectId(issue_id)})
    if not issue:
        raise ValueError("Issue not found")
        
    worker_id = issue.get("worker_id") or issue.get("assignment", {}).get("worker_id")
    if worker_id:
        try:
            w_obj = ObjectId(worker_id)
            db.users.update_one({"_id": w_obj}, {"$inc": {"active_assignments": -1}, "$set": {"is_available": True}})
            db.workers.update_one({"_id": w_obj}, {"$set": {"status": "available"}})
        except Exception:
            pass
            
    now = datetime.utcnow()
    db.issues.update_one(
        {"_id": ObjectId(issue_id)},
        {"$set": {
            "worker_id": None,
            "status": "under_review",
            "updated_at": now
        }, "$push": {
            "assignment_history": {
                "action": "unassigned",
                "officer_id": officer_id,
                "timestamp": now
            }
        }}
    )
    return db.issues.find_one({"_id": ObjectId(issue_id)})
