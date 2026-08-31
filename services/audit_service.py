"""
SmartCivic+ — Audit Trail Logging Service
"""
from bson import ObjectId
from app import db
from models.audit_log import create_audit_log_doc

def log_audit(entity_type: str, entity_id, actor_id, action: str, field_changed: str = None, old_value = None, new_value = None, reason: str = "") -> ObjectId:
    """
    Creates and records an audit log entry in db.audit_logs, returning the inserted_id.
    """
    doc = create_audit_log_doc(
        entity_type=entity_type,
        entity_id=entity_id,
        actor_id=actor_id,
        action=action,
        field_changed=field_changed,
        old_value=old_value,
        new_value=new_value,
        reason=reason
    )
    result = db.audit_logs.insert_one(doc)
    
    # Also append the audit_log ID to the entity's audit_trail if it is an issue
    if entity_type == "issue":
        db.issues.update_one(
            {"_id": ObjectId(entity_id)},
            {"$push": {"audit_trail": result.inserted_id}}
        )
        
    return result.inserted_id
