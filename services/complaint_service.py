"""
SmartCivic+ — Complaint Lifecycle Service
Manages complaint creation, AI analysis extraction, duplicate clustering, and status transitions.
"""
from datetime import datetime, timedelta
from bson import ObjectId
from app import db, socketio
from models.issue import create_issue_doc, STATUSES, CATEGORIES, DEPARTMENTS, SEVERITIES
from models.cluster import create_cluster_doc
from services import ai_service
from services.priority_service import calculate_priority
from services.sla_service import assign_sla, check_sla_status
from services.notification_service import send, COMPLAINT_CREATED, AI_ANALYSIS_COMPLETED
from services.audit_service import log_audit

LEGAL_TRANSITIONS = {
    "submitted":             ["ai_reviewed"],
    "ai_reviewed":           ["officer_reviewed"],
    "officer_reviewed":      ["assigned"],
    "assigned":              ["work_started"],
    "work_started":          ["work_completed"],
    "work_completed":        ["officer_verified", "work_started"],
    "officer_verified":      ["citizen_verification"],
    "citizen_verification":  ["closed", "reopened"],
    "reopened":              ["assigned"],
}

def recalculate_cluster_centroid(cluster_id, db):
    cluster = db.clusters.find_one({"_id": ObjectId(cluster_id)})
    if not cluster:
        return
    issues = list(db.issues.find({"_id": {"$in": cluster["issue_ids"]}}))
    if not issues:
        return
    lats = [iss["location"]["coordinates"][1] for iss in issues]
    lngs = [iss["location"]["coordinates"][0] for iss in issues]
    centroid_lat = sum(lats) / len(lats)
    centroid_lng = sum(lngs) / len(lngs)
    
    # Max severity
    sev_list = [iss.get("severity", "medium").lower() for iss in issues]
    max_sev = "low"
    for s in ["critical", "high", "medium", "low"]:
        if s in sev_list:
            max_sev = s
            break
            
    db.clusters.update_one(
        {"_id": ObjectId(cluster_id)},
        {"$set": {
            "location.coordinates": [centroid_lng, centroid_lat],
            "report_count": len(issues),
            "severity": max_sev,
            "updated_at": datetime.utcnow()
        }}
    )

def create_complaint(citizen_id, title: str, description: str, location: dict, images: list = None) -> dict:
    """
    Spawns and populates an Issue document with text/image analysis, duplicate scans, and SLA.
    """
    # Multilingual translation phase
    translation_res = ai_service.detect_and_translate(description)
    orig_lang = translation_res["detected_language"]
    trans_desc = translation_res["translated_text"]
    orig_desc = description
    
    # Use translated text for AI analysis and matching
    description = trans_desc

    coords = location.get("coordinates", [77.5946, 12.9716])
    lng, lat = coords[0], coords[1]
    
    # 1. Resolve ward from input location (or default)
    ward = location.get("ward", "Ward 1")
    address = location.get("address", "Bangalore, India")
    
    # 2. Build template doc
    issue_doc = create_issue_doc(
        citizen_id=citizen_id,
        title=title,
        description=description,
        category="other", # temporary default
        issue_type="other",
        lat=lat,
        lng=lng,
        address=address,
        ward=ward,
        images=images
    )
    issue_id = ObjectId()
    issue_doc["_id"] = issue_id
    
    # 3. AI Text Analysis
    ai_text = ai_service.analyze_complaint_text(description)
    category = ai_text.get("category", "other")
    issue_type = ai_text.get("type", "other")
    severity = ai_text.get("severity", "medium")
    department = ai_text.get("department", "roads")
    confidence = ai_text.get("confidence", 0.5)
    
    # 4. AI Image Analysis (if before image uploaded)
    image_detections = []
    if images:
        before_imgs = [img for img in images if img.get("type") == "before"]
        if before_imgs:
            # We mock resolution or resolve locally if absolute path is set
            ai_img = ai_service.analyze_complaint_image(before_imgs[0]["url"])
            image_detections = ai_img.get("image_detections", [])
            # Update severity if image detects higher critical tier
            img_sev = ai_img.get("severity", "medium")
            if img_sev in ["critical", "high"] and severity == "medium":
                severity = img_sev
                
    # 5. Duplicate check
    duplicates = ai_service.detect_duplicates(str(issue_id), description, location)
    duplicate_of = None
    cluster_id = None
    is_suppressed = False
    
    # Similarity threshold to mark duplicate
    if duplicates and duplicates[0]["similarity"] > 0.85:
        duplicate_of = ObjectId(duplicates[0]["issue_id"])
        is_suppressed = True
        
        # Add to parent's duplicate children
        db.issues.update_one(
            {"_id": duplicate_of},
            {"$addToSet": {"duplicate_children": ObjectId(issue_id)}}
        )
        
        # Link to the same cluster as original
        original = db.issues.find_one({"_id": duplicate_of})
        if original and original.get("cluster_id"):
            cluster_id = original["cluster_id"]
            db.clusters.update_one(
                {"_id": ObjectId(cluster_id)},
                {"$addToSet": {"issue_ids": ObjectId(issue_id)}}
            )
            recalculate_cluster_centroid(cluster_id, db)
    else:
        # Check if there is an existing cluster within 200m of the same category in the same ward
        from services.route_service import haversine
        existing_clusters = list(db.clusters.find({"ward": ward, "category": category, "status": "open"}))
        for c in existing_clusters:
            c_coords = c["location"]["coordinates"]
            dist = haversine((lat, lng), (c_coords[1], c_coords[0]))
            if dist < 0.2: # 200m
                cluster_id = c["_id"]
                db.clusters.update_one(
                    {"_id": ObjectId(cluster_id)},
                    {"$addToSet": {"issue_ids": ObjectId(issue_id)}}
                )
                recalculate_cluster_centroid(cluster_id, db)
                break
                
        # If no cluster found, spawn a new one
        if not cluster_id:
            cluster_doc = create_cluster_doc(
                issue_id=issue_id,
                lat=lat,
                lng=lng,
                category=category,
                issue_type=issue_type,
                severity=severity,
                ward=ward
            )
            c_res = db.clusters.insert_one(cluster_doc)
            cluster_id = c_res.inserted_id
            
    # Update issue doc with calculated AI findings and clustering refs
    ai_analysis = {
        "category": category,
        "type": issue_type,
        "severity": severity,
        "department": department,
        "confidence": confidence,
        "provider": ai_text.get("provider", "rule_based"),
        "image_detections": image_detections,
        "duplicate_candidates": duplicates,
        "analyzed_at": datetime.utcnow(),
        "officer_overridden": False,
        "override_reason": None
    }
    
    issue_doc.update({
        "category": category,
        "type": issue_type,
        "severity": severity,
        "department": department,
        "duplicate_of": duplicate_of,
        "cluster_id": cluster_id,
        "suppressed": is_suppressed,
        "original_language": orig_lang,
        "original_description": orig_desc,
        "translated_description": trans_desc,
        "ai_analysis": ai_analysis
    })
    
    # Calculate SLA & Priority
    issue_doc["sla_deadline"] = assign_sla(issue_doc)
    issue_doc["priority_score"] = calculate_priority(issue_doc, db)
    issue_doc["status"] = "ai_reviewed"
    issue_doc["updated_at"] = datetime.utcnow()
    
    db.issues.insert_one(issue_doc)
    
    # Increment Citizen Reports Submitted Count
    db.users.update_one(
        {"_id": ObjectId(citizen_id)},
        {"$inc": {"reports_submitted": 1}}
    )
    
    # Audit log & notifications
    log_audit("issue", issue_id, citizen_id, "CREATE", reason="Citizen complaint created.")
    log_audit("issue", issue_id, None, "AI_REVIEW", reason=f"AI automated parsing completed. Provider: {ai_analysis['provider']}")
    
    send(COMPLAINT_CREATED, str(citizen_id), str(issue_id))
    send(AI_ANALYSIS_COMPLETED, str(citizen_id), str(issue_id))
    
    # Run recurrence hotspot detection if not marked as duplicate
    if not duplicate_of:
        try:
            issue_doc = check_recurrence(issue_doc)
        except Exception as e:
            print(f"[Complaint Service] Recurrence check exception: {e}")
            
    # Link complaint to infrastructure segment if any matches within 100m
    try:
        from services.infrastructure_service import link_complaint_to_segment
        link_complaint_to_segment(issue_id)
        # Reload issue doc to include new field if updated
        issue_doc = db.issues.find_one({"_id": ObjectId(issue_id)})
    except Exception as e:
        print(f"[Complaint Service] Infrastructure link error: {e}")
            
    return issue_doc

def update_status(issue_id, new_status: str, actor_id, reason: str = None) -> dict:
    """
    Validates and performs issue status updates, logging audit paths and dispatching notifications.
    """
    issue = db.issues.find_one({"_id": ObjectId(issue_id)})
    if not issue:
        raise ValueError("Issue not found")
        
    old_status = issue.get("status", "submitted")
    if old_status == new_status:
        return issue
        
    # Validate transition
    allowed = LEGAL_TRANSITIONS.get(old_status, [])
    if new_status not in allowed:
        # Reopening fallback/safety
        if new_status == "reopened" and old_status == "citizen_verification":
            pass
        else:
            raise ValueError(f"Illegal status transition from {old_status} to {new_status}")
            
    now = datetime.utcnow()
    db.issues.update_one(
        {"_id": ObjectId(issue_id)},
        {"$set": {
            "status": new_status,
            "updated_at": now
        }}
    )
    
    log_audit(
        entity_type="issue",
        entity_id=issue_id,
        actor_id=actor_id,
        action="STATUS_CHANGE",
        field_changed="status",
        old_value=old_status,
        new_value=new_status,
        reason=reason or f"Status transitioned from {old_status} to {new_status}."
    )
    
    # If closed or resolved, check and update cluster status
    if new_status == "closed":
        cluster_id = issue.get("cluster_id")
        if cluster_id:
            # Check if all issues in cluster are closed
            cluster = db.clusters.find_one({"_id": ObjectId(cluster_id)})
            if cluster:
                siblings = list(db.issues.find({"_id": {"$in": cluster["issue_ids"]}}))
                if all(sib.get("status") in ["closed", "rejected"] for sib in siblings):
                    db.clusters.update_one({"_id": ObjectId(cluster_id)}, {"$set": {"status": "resolved", "updated_at": now}})
                    
    # Emit events via notification service
    # Map status value to notifications
    notif_event = None
    if new_status == "assigned":
        notif_event = "complaint_assigned"
    elif new_status == "work_started":
        notif_event = "work_started"
    elif new_status == "work_completed":
        notif_event = "work_completed"
    elif new_status == "officer_verified":
        notif_event = "officer_verified"
    elif new_status == "citizen_verification":
        notif_event = "citizen_verification_required"
    elif new_status == "closed":
        notif_event = "complaint_closed"
    elif new_status == "reopened":
        notif_event = "complaint_reopened"
        
    if notif_event:
        # Notify citizen
        send(notif_event, str(issue["citizen_id"]), str(issue_id))
        
        # Notify worker if assigned
        worker_id = issue.get("worker_id")
        if worker_id:
            send(notif_event, str(worker_id), str(issue_id))
            
    # Trigger score check after status updates
    issue["status"] = new_status
    check_sla_status(issue)
    
    return db.issues.find_one({"_id": ObjectId(issue_id)})

def declare_emergency(issue_id, declared_by_id, emergency_category: str) -> dict:
    """
    Promotes an issue to emergency critical status.
    """
    now = datetime.utcnow()
    sla_deadline = now + timedelta(hours=1)
    
    db.issues.update_one(
        {"_id": ObjectId(issue_id)},
        {"$set": {
            "is_emergency": True,
            "emergency_category": emergency_category,
            "emergency_declared_at": now,
            "emergency_declared_by": ObjectId(declared_by_id),
            "priority_score": 100.0,
            "severity": "critical",
            "sla_deadline": sla_deadline,
            "sla_status": "on_track", # resets status check window
            "updated_at": now
        }}
    )
    
    updated = db.issues.find_one({"_id": ObjectId(issue_id)})
    
    # Write audit log
    log_audit(
        entity_type="issue",
        entity_id=issue_id,
        actor_id=declared_by_id,
        action="DECLARE_EMERGENCY",
        reason=f"Emergency declared: {emergency_category}."
    )
    
    # Emit to officer room via Socket.IO in /civic namespace
    from utils import serialize
    try:
        socketio.emit(
            "emergency_declared",
            serialize(updated),
            room="officers", # broadcast to officer room
            namespace="/civic"
        )
    except Exception as e:
        print(f"[Complaint Service] Socket.IO emit emergency error: {e}")
        
    return updated

def add_community_confirmation(issue_id, citizen_id, note: str = None) -> int:
    """
    Allows citizens to confirm seeing the issue, increasing priority and duplicates count.
    """
    issue = db.issues.find_one({"_id": ObjectId(issue_id)})
    if not issue:
        raise ValueError("Issue not found")
        
    if str(issue.get("citizen_id")) == str(citizen_id):
        raise ValueError("Citizen cannot confirm their own reported issue.")
        
    if issue.get("status") not in ["submitted", "ai_reviewed", "officer_reviewed", "assigned"]:
        raise ValueError("Issue status does not allow confirmations.")
        
    # Check duplicate confirmations
    confirms = issue.get("community_confirmations", [])
    if any(str(c.get("citizen_id")) == str(citizen_id) for c in confirms):
        raise ValueError("Citizen has already confirmed this issue.")
        
    now = datetime.utcnow()
    new_confirm = {
        "citizen_id": ObjectId(citizen_id),
        "confirmed_at": now,
        "note": note.strip() if note else ""
    }
    
    db.issues.update_one(
        {"_id": ObjectId(issue_id)},
        {
            "$push": {"community_confirmations": new_confirm},
            "$inc": {"confirmation_count": 1}
        }
    )
    
    # Reload and recalculate priority score
    updated = db.issues.find_one({"_id": ObjectId(issue_id)})
    new_priority = calculate_priority(updated, db)
    db.issues.update_one(
        {"_id": ObjectId(issue_id)},
        {"$set": {"priority_score": new_priority}}
    )
    
    new_count = updated.get("confirmation_count", 0)
    
    # Write audit log
    log_audit(
        entity_type="issue",
        entity_id=issue_id,
        actor_id=citizen_id,
        action="COMMUNITY_CONFIRM",
        reason=f"Community confirmation added. Total: {new_count}."
    )
    
    # Notify officer if count crosses thresholds 5, 10, 20
    if new_count in [5, 10, 20]:
        try:
            socketio.emit(
                "notification",
                {"event_type": "high_confirmations", "message": f"Issue has reached {new_count} community confirmations.", "issue_id": str(issue_id)},
                room="officers",
                namespace="/civic"
            )
        except Exception:
            pass
            
    return new_count

def submit_feedback(issue_id, citizen_id, rating: int, feedback_text: str = None) -> dict:
    """
    Saves citizen rating and text feedback for closed issues, recalculating worker ratings.
    """
    issue = db.issues.find_one({"_id": ObjectId(issue_id)})
    if not issue:
        raise ValueError("Issue not found")
        
    if str(issue.get("citizen_id")) != str(citizen_id):
        raise ValueError("Only the original citizen who reported the issue can submit feedback.")
        
    if issue.get("status") != "closed":
        raise ValueError("Feedback can only be submitted for closed issues.")
        
    if rating < 1 or rating > 5:
        raise ValueError("Rating must be between 1 and 5 stars.")
        
    now = datetime.utcnow()
    db.issues.update_one(
        {"_id": ObjectId(issue_id)},
        {"$set": {
            "citizen_rating": rating,
            "citizen_feedback_text": feedback_text.strip() if feedback_text else "",
            "feedback_submitted_at": now
        }}
    )
    
    # Recalculate worker rating
    worker_id = issue.get("worker_id")
    if worker_id:
        worker = db.users.find_one({"_id": ObjectId(worker_id)})
        if worker:
            old_total = worker.get("total_ratings", 0)
            old_avg = worker.get("average_rating", 0.0)
            
            new_total = old_total + 1
            new_avg = ((old_avg * old_total) + float(rating)) / new_total
            
            db.users.update_one(
                {"_id": ObjectId(worker_id)},
                {"$set": {
                    "average_rating": round(new_avg, 2),
                    "total_ratings": new_total
                }}
            )
            
    # Log audit trail
    log_audit(
        entity_type="issue",
        entity_id=issue_id,
        actor_id=citizen_id,
        action="SUBMIT_FEEDBACK",
        reason=f"Feedback submitted: rating={rating} stars."
    )
    
    return db.issues.find_one({"_id": ObjectId(issue_id)})

def check_recurrence(issue: dict) -> dict:
    """
    Checks if there are 3 or more past closed issues of the same category within 200m.
    """
    category = issue.get("category")
    issue_id = issue.get("_id")
    coords = issue.get("location", {}).get("coordinates", [0.0, 0.0])
    lat, lng = coords[1], coords[0]
    
    from services.route_service import haversine
    
    # Query resolved/closed issues of the same category
    candidates = list(db.issues.find({
        "_id": {"$ne": ObjectId(issue_id)},
        "category": category,
        "status": "closed"
    }))
    
    matching_issues = []
    for cand in candidates:
        cand_coords = cand.get("location", {}).get("coordinates", [0.0, 0.0])
        dist = haversine((lat, lng), (cand_coords[1], cand_coords[0]))
        if dist < 0.2: # 200m
            matching_issues.append(cand)
            
    count = len(matching_issues)
    if count >= 3:
        # Sort by creation time to find earliest
        matching_issues.sort(key=lambda x: x.get("created_at") or datetime.utcnow())
        first_occurrence_at = matching_issues[0].get("created_at")
        
        db.issues.update_one(
            {"_id": ObjectId(issue_id)},
            {"$set": {
                "is_recurring": True,
                "recurrence_count": count,
                "first_occurrence_at": first_occurrence_at
            }}
        )
        
        # Write audit log
        log_audit(
            entity_type="issue",
            entity_id=issue_id,
            actor_id=None,
            action="RECURRENCE_DETECTED",
            reason=f"Recurring hotspot identified. Total past occurrences: {count}."
        )
        
        # Notify officer room via Socket.IO
        try:
            socketio.emit(
                "notification",
                {
                    "event_type": "recurring_detected",
                    "message": f"Recurring {category} issue hotspot detected (Ward {issue.get('ward')}).",
                    "issue_id": str(issue_id)
                },
                room="officers",
                namespace="/civic"
            )
        except Exception:
            pass
            
    return db.issues.find_one({"_id": ObjectId(issue_id)})
