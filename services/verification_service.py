"""
SmartCivic+ — Resolution Verification Service
"""
from datetime import datetime
from bson import ObjectId
from flask import current_app
from app import db
from services import ai_service
from services.complaint_service import update_status
from services.notification_service import send, WORK_COMPLETED, CITIZEN_VERIFICATION_REQ, COMPLAINT_CLOSED, COMPLAINT_REOPENED
from services.audit_service import log_audit
from models.user import derive_citizen_tier

def submit_resolution(issue_id, worker_id, before_image: dict, after_image: dict, notes: str) -> dict:
    """
    Worker submits work resolution, triggering AI verification and status updates.
    before_image & after_image: dict -> {"filename": str, "filepath": str, "url": str}
    """
    issue = db.issues.find_one({"_id": ObjectId(issue_id)})
    if not issue:
        raise ValueError("Issue not found")
        
    now = datetime.utcnow()
    
    # 1. Run AI Verification comparing before and after photos
    ai_result = ai_service.verify_resolution(
        before_image.get("filepath"),
        after_image.get("filepath"),
        issue.get("type", "other")
    )
    
    ai_verification = {
        "status": ai_result.get("status", "uncertain"),
        "confidence": ai_result.get("confidence", 0.0),
        "reasoning": ai_result.get("reasoning", ""),
        "timestamp": now
    }
    
    # Append resolution images to issue images list
    images_list = issue.get("images", [])
    
    # Add after image record
    images_list.append({
        "filename": after_image.get("filename"),
        "url": after_image.get("url"),
        "type": "after",
        "uploaded_by": ObjectId(worker_id),
        "uploaded_at": now
    })
    
    db.issues.update_one(
        {"_id": ObjectId(issue_id)},
        {
            "$set": {
                "ai_verification": ai_verification,
                "images": images_list,
                "resolution_notes": notes
            }
        }
    )
    
    # 2. Update status to work_completed
    update_status(issue_id, "work_completed", worker_id, reason="Worker completed repair task.")
    
    # 3. Log audit log & notify officer
    log_audit("issue", issue_id, worker_id, "RESOLUTION_SUBMIT", reason=f"Resolution submitted. AI Verdict: {ai_verification['status']}")
    
    officer_id = issue.get("officer_id")
    if officer_id:
        send(WORK_COMPLETED, str(officer_id), str(issue_id))
        
    return ai_verification

def officer_verify(issue_id, officer_id, approved: bool, notes: str) -> dict:
    """
    Officer reviews the worker's resolution. If approved, escalates to citizen verification.
    """
    issue = db.issues.find_one({"_id": ObjectId(issue_id)})
    if not issue:
        raise ValueError("Issue not found")
        
    if approved:
        update_status(issue_id, "officer_verified", officer_id, reason=f"Officer approved resolution: {notes}")
        # Transition to citizen verification
        update_status(issue_id, "citizen_verification", officer_id, reason="Pending citizen confirmation.")
        
        # Notify citizen
        send(CITIZEN_VERIFICATION_REQ, str(issue["citizen_id"]), str(issue_id))
    else:
        # Reject resolution - revert status to work_started so worker can repair it again
        update_status(issue_id, "work_started", officer_id, reason=f"Officer rejected resolution: {notes}")
        
        # Notify worker
        worker_id = issue.get("worker_id")
        if worker_id:
            send(COMPLAINT_REOPENED, str(worker_id), str(issue_id), extra={"note": notes})
            
    return {"success": True}

def citizen_verify(issue_id, citizen_id, resolved: bool, feedback: str) -> dict:
    """
    Citizen confirms if the issue is successfully resolved.
    """
    issue = db.issues.find_one({"_id": ObjectId(issue_id)})
    if not issue:
        raise ValueError("Issue not found")
        
    now = datetime.utcnow()
    
    if resolved:
        # Update status to closed
        update_status(issue_id, "closed", citizen_id, reason=f"Citizen confirmed resolution. Feedback: {feedback}")
        
        db.issues.update_one(
            {"_id": ObjectId(issue_id)},
            {"$set": {
                "citizen_verified": True,
                "citizen_feedback": feedback
            }}
        )
        
        # Award reputation to citizen
        db.users.update_one(
            {"_id": ObjectId(citizen_id)},
            {
                "$inc": {
                    "civic_score": 10,
                    "reports_verified_accurate": 1
                }
            }
        )
        # Refresh citizen tier
        citizen = db.users.find_one({"_id": ObjectId(citizen_id)})
        new_tier = derive_citizen_tier(citizen.get("civic_score", 0))
        db.users.update_one({"_id": ObjectId(citizen_id)}, {"$set": {"role_tier": new_tier}})
        
        # Release worker workload capacity
        worker_id = issue.get("worker_id")
        if worker_id:
            worker = db.users.find_one({"_id": ObjectId(worker_id)})
            if worker:
                active_jobs = max(0, worker.get("active_assignments", 0) - 1)
                db.users.update_one(
                    {"_id": ObjectId(worker_id)},
                    {"$set": {
                        "active_assignments": active_jobs,
                        "is_available": active_jobs < 5
                    }}
                )
                
        # Close Assignment record
        db.assignments.update_one(
            {"issue_id": ObjectId(issue_id), "status": "assigned"},
            {"$set": {
                "status": "completed",
                "completed_at": now,
                "updated_at": now
            }}
        )
        
        send(COMPLAINT_CLOSED, str(citizen_id), str(issue_id))
        send("feedback_requested", str(citizen_id), str(issue_id), extra={"message": "Please rate your experience with this issue resolution."})
    else:
        # Reopen complaint
        update_status(issue_id, "reopened", citizen_id, reason=f"Citizen disputed resolution. Feedback: {feedback}")
        
        db.issues.update_one(
            {"_id": ObjectId(issue_id)},
            {"$set": {
                "citizen_verified": False,
                "citizen_feedback": feedback
            }}
        )
        
        # Notify assigning officer or ward officer
        officer_id = issue.get("assigned_officer_id")
        if not officer_id:
            ward_officer = db.users.find_one({"role": "officer", "ward": issue.get("ward")})
            if ward_officer:
                officer_id = ward_officer["_id"]
                
        if officer_id:
            send(COMPLAINT_REOPENED, str(officer_id), str(issue_id), extra={"feedback": feedback, "role": "officer"})
            
        # Penalty/Notif for worker
        worker_id = issue.get("worker_id")
        if worker_id:
            send(COMPLAINT_REOPENED, str(worker_id), str(issue_id), extra={"feedback": feedback})
            
    return {"success": True}
