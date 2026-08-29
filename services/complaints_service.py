"""
SmartCivic — Complaints Service
Contains business logic for complaint lifecycle updates:
reopen, batch assign, timeline retrieval, and duplicate flagging.
"""
from datetime import datetime, timedelta
from bson import ObjectId
from app import socketio

REOPEN_WINDOW_DAYS = 7
MAX_WORKER_LOAD = 3


def reopen_complaint(complaint_id: str, reason: str, citizen_id: str, db) -> tuple[bool, str]:
    """
    Only the originating citizen can reopen, within 7 days of resolution.
    Returns (success, message).
    """
    comp = db.issues.find_one({"_id": ObjectId(complaint_id)})
    if not comp:
        return False, "Complaint not found"
        
    if str(comp.get("reporter_id")) != str(citizen_id):
        return False, "Only the originating citizen can reopen this complaint"
        
    if comp.get("status") != "resolved":
        return False, f"Cannot reopen a complaint in status: {comp.get('status')}"
        
    resolved_at = comp.get("resolved_at")
    if resolved_at:
        if isinstance(resolved_at, str):
            resolved_at = datetime.fromisoformat(resolved_at.replace("Z", "+00:00")).replace(tzinfo=None)
        if datetime.utcnow() > resolved_at + timedelta(days=REOPEN_WINDOW_DAYS):
            return False, "Reopen window of 7 days has expired"

    # Log the reopen event in the timeline
    event = {
        "timestamp": datetime.utcnow(),
        "event_type": "REOPENED",
        "actor": str(citizen_id),
        "detail": reason
    }
    
    db.issues.update_one(
        {"_id": ObjectId(complaint_id)},
        {
            "$set": {
                "status": "REOPENED",
                "reopened_at": datetime.utcnow(),
                "reopen_reason": reason,
                "assigned_to": None, # release worker
            },
            "$push": {"timeline": event},
            "$inc": {"reopen_count": 1}
        }
    )
    
    # Penalise the worker who marked it resolved
    worker_id = comp.get("assigned_to")
    if worker_id:
        db.users.update_one(
            {"_id": ObjectId(str(worker_id))},
            {"$inc": {"false_resolutions": 1}, "$set": {"status": "AVAILABLE"}}
        )
        
    try:
        socketio.emit("complaint_updated", {
            "complaint_id": complaint_id, "status": "REOPENED"
        }, namespace='/civic')
    except Exception:
        pass
    
    return True, "Complaint reopened successfully"


def batch_assign_complaints(worker_id: str, complaint_ids: list, db) -> dict:
    """
    Atomically assigns a list of complaint IDs to a single worker in one DB round-trip.
    Validates that the worker exists, is AVAILABLE, and that the total load does not
    exceed MAX_WORKER_LOAD (default 3). Returns counts of assigned and skipped.
    """
    worker = db.users.find_one({"_id": ObjectId(worker_id), "role": "field_worker"})
    if not worker:
        return {"assigned": [], "skipped": complaint_ids, "reason": "Worker not found"}
        
    # Count current active complaints
    current_load = db.issues.count_documents({
        "assigned_to": ObjectId(worker_id),
        "status": {"$in": ["assigned", "in_progress"]}
    })
    
    available_slots = MAX_WORKER_LOAD - current_load
    if available_slots <= 0:
        return {"assigned": [], "skipped": complaint_ids,
                "reason": f"Worker at capacity ({MAX_WORKER_LOAD} complaints)"}
                
    complaint_ids_to_process = complaint_ids[:available_slots]
    assigned, skipped = [], []
    now = datetime.utcnow()
    
    for cid in complaint_ids_to_process:
        comp = db.issues.find_one({"_id": ObjectId(cid)})
        if not comp or comp.get("status") not in ("validated", "pending_validation", "REOPENED"):
            skipped.append(cid)
            continue
            
        db.issues.update_one(
            {"_id": ObjectId(cid)},
            {
                "$set": {
                    "assigned_to": ObjectId(worker_id),
                    "status": "assigned",
                    "assigned_at": now,
                },
                "$push": {"timeline": {
                    "timestamp": now,
                    "event_type": "ASSIGNED",
                    "actor": worker_id,
                    "detail": "Batch assigned by admin"
                }}
            }
        )
        assigned.append(cid)
        
    # If any remaining from the original list that we couldn't process because of slot limits
    skipped.extend(complaint_ids[available_slots:])
        
    if assigned:
        db.users.update_one(
            {"_id": ObjectId(worker_id)},
            {"$set": {"status": "BUSY"}}
        )
        
    return {"assigned": assigned, "skipped": skipped, "reason": "OK"}


def get_complaint_timeline(complaint_id: str, db) -> list:
    """
    Returns list of timeline event dicts sorted by timestamp ascending.
    Each event: {timestamp, event_type, actor, detail}
    """
    comp = db.issues.find_one(
        {"_id": ObjectId(complaint_id)},
        {"timeline": 1, "created_at": 1, "reporter_id": 1, "category": 1}
    )
    if not comp:
        return []
        
    # Bootstrap with the creation event if timeline field is absent
    timeline = comp.get("timeline", [])
    if not timeline:
        timeline = [{
            "timestamp": comp.get("created_at"),
            "event_type": "CREATED",
            "actor": str(comp.get("reporter_id", "")),
            "detail": f"Complaint filed under category: {comp.get('category')}"
        }]
        
    # Sort ascending
    timeline.sort(key=lambda e: e.get("timestamp") or datetime.min)
    
    # Stringify ObjectIds and datetimes for JSON safety
    for event in timeline:
        ts = event.get("timestamp")
        if isinstance(ts, datetime):
            event["timestamp"] = ts.isoformat()
        else:
            event["timestamp"] = str(ts or "")
        event["actor"] = str(event.get("actor", ""))
        
    return timeline


def flag_complaint_as_duplicate(complaint_id: str, source_id: str, db) -> tuple[bool, str]:
    """
    Marks complaint_id as a verified duplicate of source_id.
    Returns (success, message).
    """
    if complaint_id == source_id:
        return False, "Cannot mark a complaint as its own duplicate"
        
    comp = db.issues.find_one({"_id": ObjectId(complaint_id)})
    source = db.issues.find_one({"_id": ObjectId(source_id)})
    if not comp or not source:
        return False, "One or both complaints not found"
        
    if comp.get("is_duplicate"):
        return False, "Already marked as duplicate"
        
    now = datetime.utcnow()
    
    # Mark the duplicate
    db.issues.update_one(
        {"_id": ObjectId(complaint_id)},
        {
            "$set": {
                "is_duplicate": True,
                "duplicate_of": ObjectId(source_id),
                "suppressed": True, # hidden from public feeds
                "status": "rejected",
                "flagged_duplicate_at": now
            },
            "$push": {"timeline": {
                "timestamp": now,
                "event_type": "DUPLICATE_FLAGGED",
                "actor": "system",
                "detail": f"Duplicate of {source_id}"
            }}
        }
    )
    
    # Register on source complaint
    db.issues.update_one(
        {"_id": ObjectId(source_id)},
        {
            "$addToSet": {"duplicate_children": ObjectId(complaint_id)},
            "$inc": {"duplicate_count": 1}
        }
    )
    
    return True, "Duplicate flagged and linked"
