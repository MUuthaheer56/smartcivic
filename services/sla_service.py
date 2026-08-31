"""
SmartCivic+ — SLA Service
Assigns and tracks complaint service level agreement (SLA) deadlines.
"""
from datetime import datetime, timedelta
from bson import ObjectId
from app import db
from models.sla import SLA_RULES, SLA_THRESHOLDS
from services.notification_service import send, SLA_WARNING, SLA_BREACHED

def assign_sla(issue: dict) -> datetime:
    """
    Sets and returns the issue's SLA deadline based on severity.
    """
    created_at = issue.get("created_at") or datetime.utcnow()
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00")).replace(tzinfo=None)
        
    if issue.get("is_emergency"):
        delta = timedelta(hours=1)
    else:
        severity = issue.get("severity", "medium").lower()
        delta = SLA_RULES.get(severity, timedelta(hours=24))
    
    deadline = created_at + delta
    return deadline

def check_sla_status(issue: dict) -> str:
    """
    Calculates elapsed percentage and updates target SLA status in DB.
    """
    created_at = issue.get("created_at")
    deadline = issue.get("sla_deadline")
    
    if not created_at or not deadline:
        return "on_track"
        
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00")).replace(tzinfo=None)
    if isinstance(deadline, str):
        deadline = datetime.fromisoformat(deadline.replace("Z", "+00:00")).replace(tzinfo=None)
        
    now = datetime.utcnow()
    total_sec = (deadline - created_at).total_seconds()
    if total_sec <= 0:
        elapsed_pct = 1.0
    else:
        elapsed_sec = (now - created_at).total_seconds()
        elapsed_pct = elapsed_sec / total_sec
        
    old_status = issue.get("sla_status", "on_track")
    new_status = "on_track"
    
    if elapsed_pct >= SLA_THRESHOLDS["breached"] or now > deadline:
        new_status = "breached"
    elif elapsed_pct >= SLA_THRESHOLDS["urgent"]:
        new_status = "urgent"
    elif elapsed_pct >= SLA_THRESHOLDS["warning"]:
        new_status = "warning"
        
    if old_status != new_status:
        db.issues.update_one(
            {"_id": issue["_id"]},
            {"$set": {"sla_status": new_status, "updated_at": now}}
        )
        
        # Trigger SLA alert notifications
        if new_status == "warning":
            send(SLA_WARNING, str(issue["citizen_id"]), str(issue["_id"]))
            # Notify assigned worker if present
            if issue.get("worker_id"):
                send(SLA_WARNING, str(issue["worker_id"]), str(issue["_id"]))
        elif new_status in ["urgent", "breached"]:
            send(SLA_BREACHED, str(issue["citizen_id"]), str(issue["_id"]))
            # Notify officer if present
            if issue.get("officer_id"):
                send(SLA_BREACHED, str(issue["officer_id"]), str(issue["_id"]))
            if issue.get("worker_id"):
                send(SLA_BREACHED, str(issue["worker_id"]), str(issue["_id"]))
                
    return new_status

def get_sla_health(ward=None, department=None) -> dict:
    """
    Returns percentage breakdowns of active issues.
    """
    query = {"status": {"$nin": ["closed", "rejected"]}}
    if ward:
        query["ward"] = ward
    if department:
        query["department"] = department
        
    total = db.issues.count_documents(query)
    if total == 0:
        return {
            "on_track_pct": 100.0,
            "warning_pct": 0.0,
            "urgent_pct": 0.0,
            "breached_pct": 0.0,
            "total": 0
        }
        
    on_track = db.issues.count_documents({**query, "sla_status": "on_track"})
    warning = db.issues.count_documents({**query, "sla_status": "warning"})
    urgent = db.issues.count_documents({**query, "sla_status": "urgent"})
    breached = db.issues.count_documents({**query, "sla_status": "breached"})
    
    return {
        "on_track_pct": round(on_track / total * 100.0, 1),
        "warning_pct": round(warning / total * 100.0, 1),
        "urgent_pct": round(urgent / total * 100.0, 1),
        "breached_pct": round(breached / total * 100.0, 1),
        "total": total
    }
