"""
SmartCivic+ — Worker Assignment Record Data Model
"""
from datetime import datetime
from bson import ObjectId

def create_assignment_doc(issue_id, worker_id, officer_id) -> dict:
    now = datetime.utcnow()
    return {
        "issue_id": ObjectId(issue_id),
        "worker_id": ObjectId(worker_id),
        "officer_id": ObjectId(officer_id),
        "status": "assigned",
        "assigned_at": now,
        "completed_at": None,
        "created_at": now,
        "updated_at": now
    }
