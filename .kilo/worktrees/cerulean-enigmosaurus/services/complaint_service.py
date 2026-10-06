import logging
import uuid
from datetime import datetime, timedelta
from bson import ObjectId
from flask import g
from app import db, socketio
from models.issue import create_issue_doc, STATUSES, CATEGORIES, DEPARTMENTS, SEVERITIES, ISSUE_STATES, validate_state_transition
from models.cluster import create_cluster_doc
from services import ai_service
from services.priority_service import calculate_priority
from services.sla_service import assign_sla, check_sla_status
from services.notification_service import send, COMPLAINT_CREATED, AI_ANALYSIS_COMPLETED
from services.audit_service import log_audit

logger = logging.getLogger(__name__)

def transition_issue_state(db, issue_id: str, new_state: str, user_id: str, notes: str = "") -> dict:
    """
    Safely transitions an issue state after validation, updating timestamps 
    and appending an audit trail log.
    """
    norm_new_state = new_state.upper().strip()
    if norm_new_state not in ISSUE_STATES and new_state.lower() not in STATUSES:
        return {"success": False, "error": f"Invalid state: {new_state}"}

    obj_id = validate_object_id(issue_id)
    issue = db.issues.find_one({"_id": obj_id}) if obj_id else db.issues.find_one({"issue_id": str(issue_id)})
    if not issue:
        return {"success": False, "error": "Issue not found"}

    current_state = issue.get("status", "SUBMITTED")

    if not validate_state_transition(current_state, new_state):
        return {
            "success": False, 
            "error": f"Illegal state transition from {current_state} to {new_state}"
        }

    now = datetime.utcnow()
    c_by = ObjectId(user_id) if (user_id and ObjectId.is_valid(str(user_id))) else str(user_id)
    audit_entry = {
        "from_state": current_state,
        "to_state": new_state,
        "changed_by": c_by,
        "timestamp": now,
        "notes": notes
    }

    result = db.issues.update_one(
        {"_id": issue["_id"]},
        {
            "$set": {"status": new_state.lower(), "updated_at": now},
            "$push": {
                "timeline_audit": audit_entry,
                "status_history": {
                    "status": new_state,
                    "timestamp": now.isoformat(),
                    "actor_id": str(user_id)
                }
            }
        }
    )

    if result.modified_count > 0:
        logger.info(f"Issue {issue_id} successfully transitioned: {current_state} -> {new_state}")
        return {"success": True, "new_state": new_state}
    
    return {"success": False, "error": "Database update failed"}

def create_new_complaint(db, citizen_id: str, description: str, location: dict, image_path: str = None) -> str:
    """
    Handles complete intake: saves initial record, runs AI pipeline + CEFAP,
    assigns SLA targets, and writes the initial structured document to MongoDB.
    """
    from services.ai_pipeline import run_unified_ai_pipeline
    from services.sla_service import assign_initial_sla

    ai_output = run_unified_ai_pipeline(description, location_text=location.get("address", "") if isinstance(location, dict) else "", image_path=image_path)
    priority = ai_output.get("priority", "P3")
    sla_deadline = assign_initial_sla(priority)

    now = datetime.utcnow()
    c_oid = ObjectId(citizen_id) if (citizen_id and ObjectId.is_valid(str(citizen_id))) else citizen_id

    issue_doc = {
        "citizen_id": c_oid,
        "description": description,
        "location": location,
        "image_path": image_path,
        "status": "AI_ANALYZED",
        "category": ai_output.get("category", "General"),
        "severity": ai_output.get("severity", "Medium"),
        "priority": priority,
        "department": ai_output.get("department", "General Services"),
        "cips_score": ai_output.get("cips_score", ai_output.get("cips", 0.0)),
        "confidence": ai_output.get("confidence_score", ai_output.get("confidence", 0.0)),
        "sla_deadline": sla_deadline,
        "assigned_worker_id": None,
        "created_at": now,
        "updated_at": now,
        "timeline_audit": [{
            "from_state": "SUBMITTED",
            "to_state": "AI_ANALYZED",
            "changed_by": c_oid,
            "timestamp": now,
            "notes": "Automated intake and AI classification complete."
        }],
        "status_history": [{
            "status": "SUBMITTED",
            "timestamp": now.isoformat(),
            "actor_id": str(citizen_id)
        }]
    }

    inserted_id = db.issues.insert_one(issue_doc).inserted_id
    return str(inserted_id)

LEGAL_TRANSITIONS = {
    "submitted":             ["under_review", "ai_reviewed", "officer_reviewed", "assigned", "rejected"],
    "ai_reviewed":           ["under_review", "officer_reviewed", "verified", "assigned", "rejected"],
    "under_review":          ["verified", "officer_reviewed", "assigned", "rejected"],
    "officer_reviewed":      ["verified", "assigned", "rejected"],
    "verified":              ["assigned", "rejected"],
    "assigned":              ["en_route", "work_started", "in_progress"],
    "en_route":              ["work_started", "in_progress", "work_completed", "resolved"],
    "work_started":          ["in_progress", "work_completed", "resolved"],
    "in_progress":           ["work_completed", "resolved"],
    "work_completed":        ["resolved", "officer_verified", "work_started", "citizen_verification", "closed"],
    "resolved":              ["officer_verified", "closed", "reopened"],
    "officer_verified":      ["citizen_verification", "closed"],
    "citizen_verification":  ["closed", "reopened"],
    "reopened":              ["assigned"],
    "duplicate":             ["under_review", "officer_reviewed", "rejected"],
}

def validate_object_id(val):
    if not val:
        return None
    val_str = str(val)
    if not ObjectId.is_valid(val_str):
        return None
    return ObjectId(val_str)

def recalculate_cluster_centroid(cluster_id, db):
    obj_cid = validate_object_id(cluster_id)
    if not obj_cid:
        return
    cluster = db.clusters.find_one({"_id": obj_cid})
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
        {"_id": obj_cid},
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
    user_ward_id = location.get("ward_id") or (getattr(g, "current_user", {}).get("ward_id") if getattr(g, "current_user", None) else None)
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
    if user_ward_id:
        issue_doc["ward_id"] = user_ward_id
        
    issue_id = ObjectId()
    issue_doc["_id"] = issue_id
    
    # 3. Analyze text and image independently before fusing the predictions.
    ai_text = ai_service.analyze_complaint_text(description)
    ai_img = None
    if images:
        before_imgs = [img for img in images if img.get("type") == "before"]
        if before_imgs:
            # Use filepath (OS path) for Pillow; fall back to url string if filepath missing
            _img_path = before_imgs[0].get("filepath") or before_imgs[0].get("url", "")
            ai_img = ai_service.analyze_complaint_image(_img_path)

    if ai_img is None:
        ai_img = {
            "available": False,
            "status": "not_requested",
            "provider": "gemini",
            "model": getattr(ai_service, "VISION_MODEL", ""),
            "reason": "No before image was uploaded.",
            "detected_issues": [],
            "detected_features": [],
            "hazards": [],
            "analyzed_at": datetime.utcnow()
        }

    final_prediction = ai_service.fuse_complaint_predictions(ai_text, ai_img)
    category = final_prediction.get("category", "other")
    issue_type = final_prediction.get("type", "other")
    severity = final_prediction.get("severity", "medium")
    department = final_prediction.get("department", "roads")
    confidence = final_prediction.get("confidence", 0.0)

    # 4. Integrate SmartCivic v2 Intelligence Pipelines
    try:
        from services.ai_classifier import classify_complaint
        from services.impact_predictor import predict_impact
        from services.authority_router import resolve_authority, compute_priority
        from services.complaint_verifier import verify_complaint
        from services.yolo_fusion import analyze_and_fuse

        v2_class = classify_complaint(description)
        
        # Fuse YOLO visual evidence if image present
        if images:
            before_imgs = [img for img in images if img.get("type") == "before"]
            if before_imgs:
                _img_path = before_imgs[0].get("filepath") or before_imgs[0].get("url", "")
                v2_class = analyze_and_fuse(_img_path, v2_class)

        v2_impact = predict_impact(
            {"severity": v2_class.get("severity", severity), "service": v2_class.get("service", category)},
            image_severity=v2_class.get("visual_evidence", {}).get("image_severity_score", 0.0) if v2_class.get("visual_evidence") else 0.0
        )
        
        v2_auth = resolve_authority(v2_class.get("service", category), v2_class.get("issue_type", issue_type), ward)
        v2_prio = compute_priority(v2_class.get("service", category), v2_class.get("severity", severity), v2_class.get("emergency", False))

        issue_doc.update({
            "service": v2_class.get("service", category),
            "issue_type": v2_class.get("issue_type", issue_type),
            "ai_confidence": v2_class.get("confidence", confidence),
            "ai_route_decision": v2_class.get("route_decision"),
            "priority": v2_prio,
            "emergency": v2_class.get("emergency", False),
            "emergency_state": v2_class.get("emergency_state"),
            "impact": v2_impact,
            "authority_primary": v2_auth.get("authority_id"),
            "authority_secondary": v2_auth.get("secondary", []),
            "visual_evidence": v2_class.get("visual_evidence")
        })

        v2_ver = verify_complaint(issue_doc, v2_class)
        issue_doc.update(v2_ver)
    except Exception as e:
        print(f"[v2 Pipeline Warning] {e}")

    # 5. Duplicate check
    duplicates = ai_service.detect_duplicates(str(issue_id), description, location)
    duplicate_of = None
    cluster_id = None
    is_suppressed = False
    
    if duplicates and duplicates[0]["similarity"] >= 0.85:
        matched_raw = duplicates[0]["issue_id"]
        duplicate_of = ObjectId(matched_raw) if ObjectId.is_valid(matched_raw) else matched_raw
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
        "image_analysis": ai_img,
        "text_analysis": ai_text,
        "final_prediction": final_prediction,
        "category": category,
        "type": issue_type,
        "severity": severity,
        "department": department,
        "confidence": confidence,
        "confidence_type": final_prediction.get("confidence_type", "heuristic"),
        "provider": ai_img.get("provider") if ai_img.get("available") else ai_text.get("provider", "rule_based"),
        "model": ai_img.get("model") if ai_img.get("available") else None,
        "image_analysis_available": bool(ai_img.get("available")),
        "image_detections": ai_img.get("image_detections", []),
        "explanation": final_prediction.get("reason", ""),
        "category_source": "model_predicted" if ai_img.get("available") else "text_analysis",
        "department_source": "category_mapping",
        "duplicate_candidates": duplicates,
        "analyzed_at": datetime.utcnow(),
        "officer_overridden": False,
        "override_reason": None,
        "ai_prediction": dict(final_prediction),
        "officer_override": None,
        "final_operational_value": dict(final_prediction)
    }
    
    dup_info = {
        "is_duplicate": is_suppressed,
        "matched_issue_id": str(duplicate_of) if duplicate_of else None,
        "similarity": duplicates[0]["similarity"] if duplicates else 0.0
    }
    
    now = datetime.utcnow()
    formatted_issue_id = f"SC-2026-{str(uuid.uuid4().hex[:6]).upper()}"
    
    img_info = {}
    if images:
        img_info = {"url": images[0].get("url"), "filename": images[0].get("filename")}

    issue_doc.update({
        "issue_id": formatted_issue_id,
        "category": category,
        "type": issue_type,
        "severity": severity,
        "department": department,
        "duplicate_of": duplicate_of,
        "duplicate": dup_info,
        "cluster_id": cluster_id,
        "suppressed": is_suppressed,
        "original_language": orig_lang,
        "original_description": orig_desc,
        "translated_description": trans_desc,
        "ai_analysis": ai_analysis,
        "ai_prediction": {
            "issue_type": issue_type,
            "category": category,
            "severity": severity,
            "department": department,
            "confidence": confidence,
            "confidence_type": final_prediction.get("confidence_type", "heuristic")
        },
        "priority": severity,
        "image": img_info,
        "location": {
            "type": "Point",
            "coordinates": [float(lng), float(lat)]
        },
        "latitude": float(lat),
        "longitude": float(lng),
        "address": address,
        "ward": ward,
        "status_history": [
            {"status": "submitted", "timestamp": now.isoformat()}
        ]
    })
    
    # Deferred SLA calculation after category & severity assignment
    sla_dl = assign_sla(issue_doc)
    sla_info = {
        "deadline": sla_dl.isoformat() if hasattr(sla_dl, "isoformat") else str(sla_dl),
        "breached": False
    }
    issue_doc["sla"] = sla_info
    issue_doc["sla_deadline"] = sla_dl

    if is_suppressed:
        issue_doc["status"] = "duplicate"
    else:
        issue_doc["status"] = "submitted"
    try:
        from services.cefap_pipeline import cefap_stage
        cefap_res = cefap_stage(db, {
            "issue_id": formatted_issue_id,
            "ward_id": issue_doc.get("ward_id") or ward.lower().replace(" ", "_"),
            "service": issue_doc.get("service") or category or "road",
            "text_severity": issue_doc.get("severity", "medium"),
            "text_confidence": issue_doc.get("ai_confidence", 0.70),
            "image_severity": None,
            "image_confidence": None,
            "location_type": location.get("location_type", "unknown"),
            "vote_count": 0,
            "historical_complaints": [],
            "created_at": now,
            "sla_deadline": sla_dl
        })
        issue_doc.update({
            "cips_score": cefap_res["cips"],
            "priority": cefap_res["priority"],
            "evidence_reliability": cefap_res["evidence_reliability"],
            "evidence_agreement": cefap_res["evidence_agreement"],
            "ctve_triggered": cefap_res["ctve_triggered"],
            "ctve_message": cefap_res["ctve_message"],
            "verification_required": cefap_res["verification_required"],
            "monsoon_active": cefap_res["monsoon"]["active"],
        })
    except Exception as ex:
        print(f"[CEFAP Integration Warning] {ex}")

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

def update_status(issue_id, new_status: str, actor_id, reason: str = None, actor_role: str = None) -> dict:
    """
    Validates and performs issue status updates with actor role permission enforcement.
    """
    obj_id = validate_object_id(issue_id)
    issue = db.issues.find_one({"_id": obj_id}) if obj_id else db.issues.find_one({"issue_id": str(issue_id)})
        
    if not issue:
        raise ValueError("Issue not found")
        
    old_status = issue.get("status", "submitted")
    if old_status == new_status:
        return issue

    if actor_role in ["citizen", "resident"] and new_status in ["resolved", "closed", "officer_verified", "verified"]:
        raise ValueError("Unauthorized status transition for citizen role.")

    # Validate transition
    allowed = LEGAL_TRANSITIONS.get(old_status, [])
    if new_status not in allowed:
        # Reopening fallback/safety
        if new_status == "reopened" and old_status == "citizen_verification":
            pass
        else:
            raise ValueError(f"Illegal status transition from {old_status} to {new_status}")
            
    now = datetime.utcnow()
    status_entry = {
        "status": new_status,
        "timestamp": now.isoformat(),
        "actor_id": str(actor_id) if actor_id else None
    }
    db.issues.update_one(
        {"_id": issue["_id"]},
        {"$set": {
            "status": new_status,
            "updated_at": now
        }, "$push": {
            "status_history": status_entry
        }}
    )
    
    log_audit(
        entity_type="issue",
        entity_id=str(issue["_id"]),
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
        citizen_id = issue.get("citizen_id")
        if citizen_id:
            send(notif_event, str(citizen_id), str(issue_id))
        
        # Notify worker if assigned
        worker_id = issue.get("worker_id")
        if worker_id:
            send(notif_event, str(worker_id), str(issue_id))
            
    # Trigger score check after status updates
    issue["status"] = new_status
    check_sla_status(issue)
    
    return db.issues.find_one({"_id": issue["_id"]})

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
            room="role_officer", # broadcast to officer room
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
        
    if issue.get("status") in ["closed", "rejected", "resolved", "duplicate"]:
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
                room="role_officer",
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
                room="role_officer",
                namespace="/civic"
            )
        except Exception:
            pass
            
    return db.issues.find_one({"_id": ObjectId(issue_id)})

def get_complaint(issue_id: str) -> dict:
    try:
        obj_id = ObjectId(issue_id)
        issue = db.issues.find_one({"_id": obj_id})
    except Exception:
        issue = None
    if not issue:
        issue = db.issues.find_one({"issue_id": issue_id})
    if not issue:
        raise ValueError(f"Complaint not found for ID '{issue_id}'")
    issue["issue_id"] = str(issue["_id"])
    return issue

def list_complaints(filters: dict = None) -> list:
    query = {}
    if filters:
        if "category" in filters and filters["category"]:
            query["category"] = filters["category"]
        if "status" in filters and filters["status"]:
            query["status"] = filters["status"]
        if "ward" in filters and filters["ward"]:
            query["ward"] = filters["ward"]
        if "citizen_id" in filters and filters["citizen_id"]:
            try:
                query["citizen_id"] = ObjectId(filters["citizen_id"])
            except Exception:
                query["citizen_id"] = filters["citizen_id"]
        if "worker_id" in filters and filters["worker_id"]:
            try:
                query["worker_id"] = ObjectId(filters["worker_id"])
            except Exception:
                query["worker_id"] = filters["worker_id"]
                
    issues = list(db.issues.find(query).sort("created_at", -1))
    for i in issues:
        i["issue_id"] = str(i["_id"])
    return issues

def update_complaint(issue_id: str, updates: dict, actor: dict = None) -> dict:
    get_complaint(issue_id) # validates complaint existence
    try:
        obj_id = ObjectId(issue_id)
    except Exception:
        raise ValueError("Invalid issue ID format.")
        
    updates["updated_at"] = datetime.utcnow()
    db.issues.update_one({"_id": obj_id}, {"$set": updates})
    return get_complaint(issue_id)
