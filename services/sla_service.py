from datetime import datetime, timedelta

SLA_DAYS = {
    'water': 1,
    'sewage': 1,
    'garbage': 2,
    'streetlight': 3,
    'noise': 5,
    'pothole': 7,
    'other': 7
}

def get_sla_deadline(category: str, created_at: datetime) -> datetime:
    days = SLA_DAYS.get(category, 7)
    return created_at + timedelta(days=days)

def get_sla_status(issue: dict) -> dict:
    deadline = issue.get('sla_deadline')
    created_at = issue.get('created_at')
    category = issue.get('category', 'other')
    
    if isinstance(deadline, str):
        try:
            deadline = datetime.fromisoformat(deadline.replace('Z', '+00:00')).replace(tzinfo=None)
        except Exception:
            deadline = None
            
    if isinstance(created_at, str):
        try:
            created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00')).replace(tzinfo=None)
        except Exception:
            created_at = None
            
    now = datetime.utcnow()
    
    if not deadline:
        return {
            'deadline_iso': None,
            'days_remaining': None,
            'is_overdue': False,
            'percent_elapsed': 0.0,
            'sla_days': SLA_DAYS.get(category, 7)
        }
        
    days_remaining = (deadline - now).days
    # If same day, check hours or fallback
    if days_remaining == 0:
        # Check hours remaining
        hours = (deadline - now).total_seconds() / 3600
        days_remaining = round(hours / 24.0, 2)
        
    is_overdue = now > deadline
    
    percent_elapsed = 0.0
    if created_at:
        total_sec = (deadline - created_at).total_seconds()
        if total_sec > 0:
            elapsed_sec = (now - created_at).total_seconds()
            percent_elapsed = min(100.0, max(0.0, (elapsed_sec / total_sec) * 100))
            
    return {
        'deadline_iso': deadline.isoformat(),
        'days_remaining': days_remaining,
        'is_overdue': is_overdue,
        'percent_elapsed': round(percent_elapsed, 1),
        'sla_days': SLA_DAYS.get(category, 7)
    }

def check_and_flag_sla_breaches():
    from app import db
    from services.score_service import apply_score_change
    from services.notification_service import notify_authority_room
    
    now = datetime.utcnow()
    # Find all unresolved (not in 'resolved', 'rejected') issues where deadline has passed and sla_breached is False
    unresolved_statuses = ['pending_validation', 'validated', 'assigned', 'in_progress']
    breached_issues = list(db.issues.find({
        'status': {'$in': unresolved_statuses},
        'sla_deadline': {'$lt': now},
        'sla_breached': {'$ne': True}
    }))
    
    for issue in breached_issues:
        db.issues.update_one(
            {'_id': issue['_id']},
            {'$set': {'sla_breached': True}}
        )
        apply_score_change(str(issue['community_id']), -3, f"SLA breached: {issue['title']}")
        
        # Notify authority room via SocketIO
        data = {
            'issue_id': str(issue['_id']),
            'title': issue['title'],
            'category': issue['category'],
            'severity': issue.get('severity', 3)
        }
        notify_authority_room(str(issue['community_id']), 'sla_breach', data)

from bson import ObjectId
from ai.analytics import compute_worker_performance

def escalate_sla_breach(complaint_id: str, db) -> dict:
    """
    Escalates an SLA-breached complaint.
    Returns {"escalated": bool, "escalation_level": int, "new_assignee": str|None}
    """
    comp = db.issues.find_one({"_id": ObjectId(complaint_id)})
    if not comp:
        return {"escalated": False, "escalation_level": 0, "new_assignee": None}
        
    current_level = comp.get("escalation_level", 0)
    MAX_ESCALATION_LEVEL = 3
    if current_level >= MAX_ESCALATION_LEVEL:
        return {"escalated": False, "escalation_level": current_level, "new_assignee": None}
        
    new_level = current_level + 1
    now = datetime.utcnow()
    new_assignee = None
    
    updates = {
        "$set": {"escalation_level": new_level, "sla_status": "BREACHED"},
        "$push": {"timeline": {
            "timestamp": now,
            "event_type": "SLA_BREACH_ESCALATED",
            "actor": "system",
            "detail": f"Escalation level {new_level}"
        }}
    }
    
    # On level 2+, try to reassign to best available worker
    if new_level >= 2:
        ward = comp.get("community_id") or comp.get("ward")
        category = comp.get("category")
        best = _find_best_available_worker(ward, category, db)
        if best and str(best["_id"]) != str(comp.get("assigned_to", "")):
            new_assignee = str(best["_id"])
            updates["$set"]["assigned_to"] = best["_id"]
            updates["$set"]["status"] = "assigned"
            db.users.update_one({"_id": best["_id"]}, {"$set": {"status": "BUSY"}})
            
            old_worker_id = comp.get("assigned_to")
            if old_worker_id:
                db.users.update_one({"_id": ObjectId(old_worker_id)}, {"$set": {"status": "AVAILABLE"}})
                
    db.issues.update_one({"_id": ObjectId(complaint_id)}, updates)
    
    # Notify ward admins
    admin_filter = {"role": "authority"}
    comp_comm_id = comp.get("community_id")
    if comp_comm_id:
        admin_filter["community_id"] = ObjectId(comp_comm_id)
    admins = list(db.users.find(admin_filter))
    
    for admin in admins:
        db.notifications.insert_one({
            "user_id": admin["_id"],
            "complaint_id": ObjectId(complaint_id),
            "message": f"SLA breach level {new_level}: {comp.get('category')} complaint in {comp.get('ward') or 'your community'} has exceeded its deadline.",
            "is_read": False,
            "created_at": now,
            "delivery_status": "PENDING"
        })
        
    return {"escalated": True, "escalation_level": new_level, "new_assignee": new_assignee}

def _find_best_available_worker(ward, category, db):
    """Returns the highest-performing available worker for the ward/category."""
    query = {"role": "field_worker", "status": "AVAILABLE"}
    if isinstance(ward, str) and ObjectId.is_valid(ward):
        query["community_id"] = ObjectId(ward)
    elif ObjectId.is_valid(str(ward)):
        query["community_id"] = ObjectId(str(ward))
    else:
        query["ward"] = ward
        
    from services.workers_service import DEPT_CATEGORY_MAP
    dept = DEPT_CATEGORY_MAP.get(category)
    if dept:
        query["department"] = dept
        
    candidates = list(db.users.find(query))
    if not candidates:
        return None
        
    scored = []
    for w in candidates:
        perf = compute_worker_performance(str(w["_id"]), db)
        scored.append((perf.get("score", 0), w))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1] if scored else None
