"""
SmartCivic v2 — SLA Escalation & Background Monitor
Monitors open issues against SLA deadlines (P0: 1h, P1: 4h, P2: 24h, P3: 72h) and triggers escalations.
"""
from datetime import datetime, timedelta
from app import db, socketio

SLA_HOURS = {
    "P0": 1,
    "P1": 4,
    "P2": 24,
    "P3": 72,
}

def run_escalation_check():
    """
    Background worker task called periodically by APScheduler.
    Evaluates SLA deadlines for all active, non-emergency complaints.
    """
    now = datetime.utcnow()
    try:
        active = list(db.issues.find({
            "status": {"$nin": ["closed", "CLOSED", "REJECTED", "work_completed", "officer_verified"]},
            "emergency": False
        }))
    except Exception as e:
        print(f"[SLA Scheduler] Error querying active issues: {e}")
        return

    for complaint in active:
        priority = complaint.get("priority", "P3")
        sla_hours = SLA_HOURS.get(priority, 72)
        created_at = complaint.get("created_at") or now
        deadline = created_at + timedelta(hours=sla_hours)

        if now > deadline:
            current_level = complaint.get("escalation_level", 0)
            if current_level < 3:
                new_level = current_level + 1
                complaint_id = str(complaint["_id"])
                
                # Atomic conditional update matching exact current escalation level
                res = db.issues.update_one(
                    {
                        "_id": complaint["_id"],
                        "escalation_level": current_level
                    },
                    {
                        "$set": {
                            "escalation_level": new_level,
                            "sla_status": "breached"
                        },
                        "$push": {
                            "status_history": {
                                "status": f"ESCALATED_L{new_level}",
                                "timestamp": now,
                                "actor": "system",
                                "note": f"SLA breached ({sla_hours}h limit). Escalation level {new_level}."
                            }
                        }
                    }
                )

                # Broadcast SLA breach alert ONLY if this background process updated the document
                if res.modified_count > 0:
                    try:
                        socketio.emit("sla_breach", {
                            "issue_id": complaint_id,
                            "complaint_id": complaint_id,
                            "priority": priority,
                            "escalation_level": new_level,
                            "sla_hours": sla_hours
                        }, room="officers")
                    except Exception:
                        pass
