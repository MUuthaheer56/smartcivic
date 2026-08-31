"""
SmartCivic+ — Audit Log Data Model
Logs every sensitive database update/alteration.
"""
from datetime import datetime
from bson import ObjectId

def create_audit_log_doc(entity_type: str, entity_id, actor_id, action: str, field_changed: str = None, old_value = None, new_value = None, reason: str = "") -> dict:
    return {
        "entity_type": entity_type, # issue, user, assignment
        "entity_id": ObjectId(entity_id),
        "actor_id": ObjectId(actor_id) if actor_id else None,
        "action": action,
        "field_changed": field_changed,
        "old_value": old_value,
        "new_value": new_value,
        "reason": reason,
        "timestamp": datetime.utcnow()
    }
