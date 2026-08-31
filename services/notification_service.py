"""
SmartCivic+ — Central Notification Service
Replaces all other notification engines. Broadcasts via Socket.IO and saves to MongoDB.
"""
from datetime import datetime
from bson import ObjectId
from app import db, socketio
from utils import serialize

COMPLAINT_CREATED          = "complaint_created"
AI_ANALYSIS_COMPLETED      = "ai_analysis_completed"
COMPLAINT_ASSIGNED         = "complaint_assigned"
WORK_STARTED               = "work_started"
WORK_COMPLETED             = "work_completed"
OFFICER_VERIFIED           = "officer_verified"
CITIZEN_VERIFICATION_REQ   = "citizen_verification_required"
COMPLAINT_CLOSED           = "complaint_closed"
COMPLAINT_REOPENED         = "complaint_reopened"
SLA_WARNING                = "sla_warning"
SLA_BREACHED               = "sla_breached"

EVENT_MESSAGES = {
    COMPLAINT_CREATED: "Your complaint has been successfully submitted and is under review.",
    AI_ANALYSIS_COMPLETED: "AI analysis has processed your issue.",
    COMPLAINT_ASSIGNED: "A field worker has been assigned to your issue.",
    WORK_STARTED: "Work has officially started on your complaint.",
    WORK_COMPLETED: "Work is completed. Please verify the resolution.",
    OFFICER_VERIFIED: "Officer has verified the resolution of the complaint.",
    CITIZEN_VERIFICATION_REQ: "Action required: Please verify if the complaint is fixed.",
    COMPLAINT_CLOSED: "Your complaint has been closed successfully.",
    COMPLAINT_REOPENED: "The complaint has been reopened.",
    SLA_WARNING: "SLA Warning: An active issue is approaching its deadline.",
    SLA_BREACHED: "SLA Breach: An issue has exceeded its target resolution SLA deadline."
}

def send(event: str, recipient_id: str, issue_id: str = None, extra: dict = None):
    """
    Creates and records a notification in db.notifications and emits via Socket.IO.
    """
    now = datetime.utcnow()
    msg = EVENT_MESSAGES.get(event, f"Notification: {event}")
    
    notif_doc = {
        "user_id": ObjectId(recipient_id),
        "issue_id": ObjectId(issue_id) if issue_id else None,
        "event_type": event,
        "message": msg,
        "extra": extra or {},
        "is_read": False,
        "created_at": now
    }
    
    db.notifications.insert_one(notif_doc)
    
    delivery_status = "delivered"
    err_msg = None
    # Emit to target user room in /civic namespace
    try:
        socketio.emit(
            "notification",
            serialize(notif_doc),
            room=f"user_{recipient_id}",
            namespace="/civic"
        )
    except Exception as e:
        delivery_status = "failed"
        err_msg = str(e)
        print(f"[Notification Service] Socket.IO emit error: {e}")
        
    try:
        from services.logger_service import log_notification
        log_notification(event, recipient_id, delivery_status, err_msg)
    except Exception:
        pass
        
    return notif_doc
