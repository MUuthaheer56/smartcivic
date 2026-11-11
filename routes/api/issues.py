"""
SmartCivic+ — Issues API Blueprint
Handles complaint CRUD, uploads with MIME validation, and status updates.
"""
from flask import Blueprint, request, jsonify, g, current_app
from bson import ObjectId
import os
import uuid
import math
try:
    import magic
except Exception:
    magic = None
from datetime import datetime, timedelta
from config import Config
from app import db, limiter
from routes.auth import require_auth, require_role
from utils.auth_helpers import verified_required, authorize_issue_access
from models.issue import IssueCreateSchema, CATEGORIES, SEVERITIES, DEPARTMENTS, normalize_priority
from services import complaint_service, assignment_service, verification_service, sla_service
from services.audit_service import log_audit
from utils import serialize, parse_object_id

issues_api_bp = Blueprint('issues_api', __name__)

def validate_image_file(file):
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in current_app.config.get("ALLOWED_EXTENSIONS", {"jpg", "jpeg", "png", "webp"}):
        return False, "Invalid file extension"
        
    # Check file size (5MB cap)
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0) # reset
    if size > current_app.config.get("MAX_UPLOAD_SIZE", 5 * 1024 * 1024):
        return False, "File exceeds maximum size limits (5MB)."
        
    # Validate MIME type / header
    header = file.read(2048)
    file.seek(0)
    
    if magic is not None:
        try:
            mime = magic.from_buffer(header, mime=True)
            if mime in {"image/jpeg", "image/png", "image/webp"}:
                return True, None
        except Exception as e:
            print(f"[Security Check] python-magic exception: {e}")
            
    # PIL Fallback for image verification
    try:
        from PIL import Image
        import io
        content = file.read()
        file.seek(0)
        img = Image.open(io.BytesIO(content))
        img.verify()
        if img.format and img.format.lower() in {"jpeg", "png", "webp", "mpo"}:
            return True, None
    except Exception as e:
        print(f"[Security Check] PIL fallback exception: {e}")

    return False, "Unable to verify image content. Please upload a valid JPEG, PNG, or WebP image."

@issues_api_bp.route('/api/issues', methods=['POST'])
@require_auth
@verified_required
@require_role('citizen', 'resident')
@limiter.limit("10 per hour")
def create_issue():
    payload = request.form if request.form else (request.get_json(silent=True) or {})
    description = payload.get("description")
    if not isinstance(description, str) or len(description.strip()) < 10:
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": "description must be at least 10 characters."}}), 400

    lat_val = payload.get("latitude")
    if lat_val is None:
        lat_val = payload.get("lat")
    lng_val = payload.get("longitude")
    if lng_val is None:
        lng_val = payload.get("lng")
    location_provided = lat_val is not None and lng_val is not None

    if not location_provided and 'image' in request.files:
        try:
            from services.ai.image_gate import extract_exif_gps
            img_file = request.files['image']
            exif_coords = extract_exif_gps(img_file)
            if exif_coords:
                lat_val = exif_coords["latitude"]
                lng_val = exif_coords["longitude"]
                location_provided = True
        except Exception:
            pass
    
    try:
        lat = float(lat_val) if lat_val is not None else 12.9716
        lng = float(lng_val) if lng_val is not None else 77.5946
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": "Invalid latitude or longitude."}}), 400
    if not math.isfinite(lat) or not math.isfinite(lng) or not -90 <= lat <= 90 or not -180 <= lng <= 180:
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": "Invalid latitude or longitude."}}), 400

    address = payload.get("address") or "MG Road, Bengaluru"
    title = payload.get("title") or (description[:40] + "...")
    category = payload.get("category")
    if category not in CATEGORIES:
        category = None
    issue_type = payload.get("type")
    if not isinstance(issue_type, str) or not 2 <= len(issue_type.strip()) <= 80:
        issue_type = None
    ward = payload.get("ward") or "Ward 1"
    citizen_ward = g.current_user.get("ward")
    if citizen_ward and str(citizen_ward).strip().lower() not in ('all', '*', ''):
        ward = citizen_ward
    
    images = []
    if 'image' in request.files:
        file = request.files['image']
        if file and file.filename:
            upload_dir = current_app.config.get("UPLOAD_FOLDER", os.path.join(current_app.root_path, "uploads", "issues"))
            try:
                from utils.image_utils import save_uploaded_image
                img_info = save_uploaded_image(file, upload_dir)
                images.append({
                    "filename": img_info["filename"],
                    "filepath": img_info["filepath"],
                    "url": img_info["url"],
                    "type": "before",
                    "uploaded_by": ObjectId(g.current_user["_id"]),
                    "uploaded_at": datetime.utcnow()
                })
            except ValueError as ve:
                return jsonify({"success": False, "error": {"code": "SECURITY_ERROR", "message": str(ve)}}), 400
            except Exception as ex:
                return jsonify({"success": False, "error": {"code": "SECURITY_ERROR", "message": "Invalid or corrupt image file."}}), 400

            
    location = {
        "type": "Point",
        "coordinates": [lng, lat],
        "latitude": lat,
        "longitude": lng,
        "ward": ward,
        "ward_id": g.current_user.get("ward_id") if hasattr(g, "current_user") and g.current_user else None,
        "address": address,
        "provided": location_provided,
    }
    
    is_anon = payload.get("is_anonymous") in [True, "true", "True", "1", 1]
    try:
        issue = complaint_service.create_complaint(
            citizen_id=None if is_anon else str(g.current_user["_id"]),
            title=title,
            description=description,
            location=location,
            images=images,
            category=category,
            issue_type=issue_type,
            is_anonymous=is_anon
        )

        if is_anon:
            import hmac
            import hashlib
            user_id_str = str(g.current_user["_id"])
            secret_key = current_app.config.get("SECRET_KEY", "default-salt").encode("utf-8")
            reporter_hash = hmac.new(secret_key, user_id_str.encode("utf-8"), hashlib.sha256).hexdigest()
            db.anonymous_reporters.insert_one({
                "issue_id": issue["_id"],
                "reporter_hash": reporter_hash,
                "created_at": datetime.utcnow()
            })
        
        if images:
            old_filepath = os.path.join(current_app.config["UPLOAD_FOLDER"], images[0]["filename"])
            ext = images[0]["filename"].rsplit('.', 1)[-1].lower() if '.' in images[0]["filename"] else 'jpg'
            new_filename = f"{uuid.uuid4().hex}.{ext}"
            new_filepath = os.path.join(current_app.config["UPLOAD_FOLDER"], new_filename)
            if os.path.exists(old_filepath):
                os.rename(old_filepath, new_filepath)
                
            images[0]["filename"] = new_filename
            images[0]["filepath"] = new_filepath
            images[0]["url"] = f"/files/issues/{new_filename}"
            db.issues.update_one({"_id": issue["_id"]}, {"$set": {
                "images": images,
                "image": {"url": images[0]["url"], "filename": new_filename}
            }})
            issue["image"] = {"url": images[0]["url"], "filename": new_filename}
            
        # Phase 3: Image Trust Gate evaluation (behind AI_IMAGE_GATE_ENABLED)
        image_gate_result = None
        if images and os.path.exists(images[0]["filepath"]):
            try:
                from services.ai.image_gate import evaluate_image_quality, store_image_hash
                image_gate_result = evaluate_image_quality(
                    images[0]["filepath"],
                    issue_id=str(issue["_id"]),
                    user_id=str(g.current_user["_id"]),
                    db=db
                )
                
                gate_val = image_gate_result.get("value", {})
                passed = gate_val.get("passed", True)
                
                # Check emergency fast lane (Rule R8: never block emergencies)
                norm_p = normalize_priority(issue.get("priority"))
                emerg_val = issue.get("emergency_state")
                is_emergency = (
                    (norm_p == "P0")
                    or bool(issue.get("emergency", False))
                    or bool(issue.get("is_emergency", False))
                    or (bool(emerg_val.get("is_emergency", False)) if isinstance(emerg_val, dict) else bool(emerg_val))
                )
                
                # Store perceptual hash for reuse detection
                dhash_val = gate_val.get("metrics", {}).get("hash")
                if dhash_val:
                    store_image_hash(db, dhash_val, str(issue["_id"]), str(g.current_user["_id"]), gate_val.get("metrics"))

                # Log decision to db.ai_decisions
                from services.ai.decision_logger import log_ai_decision
                log_ai_decision(
                    db=db,
                    issue_id=str(issue["_id"]),
                    stage="image_gate",
                    envelope=image_gate_result,
                    model_version="image_gate_v1"
                )

                is_gate_enabled = current_app.config.get("AI_IMAGE_GATE_ENABLED", False) or getattr(Config, "AI_IMAGE_GATE_ENABLED", False)
                if is_gate_enabled:
                    if not passed and not is_emergency:
                        # Non-emergency quality issue triggers CTVE clarification
                        ctve_msg = gate_val.get("clarification_message") or "Your uploaded photo appears unclear. Please upload a clearer photo."
                        db.issues.update_one({"_id": issue["_id"]}, {"$set": {
                            "ctve_triggered": True,
                            "ctve_message": ctve_msg,
                            "image_gate_flags": gate_val.get("issues", [])
                        }})
                        issue["ctve_triggered"] = True
                        issue["ctve_message"] = ctve_msg
                        issue["image_gate_flags"] = gate_val.get("issues", [])
            except Exception as gate_err:
                current_app.logger.warning(f"Image gate evaluation error: {gate_err}")

        try:
            from utils.civic_score import apply_score_delta
            apply_score_delta(db, str(g.current_user["_id"]), "report_filed")
        except Exception:
            pass

        # Enqueue background async AI analysis (non-blocking)
        img_path = images[0]["filepath"] if images else None
        reporter_verified = bool(g.current_user.get("verified", False))
        user_ward_id = g.current_user.get("ward_id") or "ward_1"
        try:
            from services.ai_pipeline import enqueue_ai_analysis
            enqueue_ai_analysis(current_app._get_current_object(), str(issue["_id"]), description, address, img_path, reporter_verified, user_ward_id)
        except Exception as async_err:
            current_app.logger.warning(f"Enqueue async AI error: {async_err}")


        cefap_doc = db.cefap_results.find_one({"$or": [{"issue_id": str(issue.get("_id"))}, {"issue_id": issue.get("issue_id")}]}, {"_id": 0})
        signals = {
            "text_severity": issue.get("text_severity") or (cefap_doc.get("text_severity") if cefap_doc else None),
            "image_severity": issue.get("image_severity") or (cefap_doc.get("image_severity") if cefap_doc else None),
            "location_impact": issue.get("location_impact") or (cefap_doc.get("location_impact") if cefap_doc else None),
            "corroboration": issue.get("corroboration") or (cefap_doc.get("corroboration") if cefap_doc else None),
            "recurrence": issue.get("recurrence") or (cefap_doc.get("recurrence") if cefap_doc else None),
            "sla_risk": issue.get("sla_risk") or (cefap_doc.get("sla_risk") if cefap_doc else None),
        }
        from utils.serializers import serialize_citizen_issue
        res_data = serialize_citizen_issue(issue, user_id=str(g.current_user["_id"]))
        res_data["signals"] = signals
        return jsonify({
            "success": True,
            "message": "Complaint submitted successfully.",
            "issue_id": issue.get("issue_id") or str(issue["_id"]),
            "status": issue.get("status", "submitted"),
            "ai_detected": issue.get("ai_detected"),
            "ai_prediction": issue.get("ai_prediction", {}),
            "duplicate": issue.get("duplicate", {"is_duplicate": False}),
            "priority": normalize_priority(issue.get("priority")),
            "priority_score": issue.get("priority_score", 0.0),
            "priority_decision": issue.get("priority_decision", {}),
            "cips_score": issue.get("cips_score"),
            "evidence_reliability": issue.get("evidence_reliability"),
            "evidence_agreement": issue.get("evidence_agreement"),
            "ctve_triggered": issue.get("ctve_triggered", False),
            "ctve_message": issue.get("ctve_message"),
            "image_gate": image_gate_result.get("value") if image_gate_result else None,
            "verification_required": issue.get("verification_required", False),
            "signals": signals,
            "sla": issue.get("sla", {}),
            "image": issue.get("image", {}),
            "location": {"latitude": lat, "longitude": lng, "address": address},
            "data": res_data
        }), 201
    except Exception as e:
        print(f"[create_issue ERROR] {e}", flush=True)
        current_app.logger.exception(e)
        return jsonify({"success": False, "error": {"code": "SERVER_ERROR", "message": "An internal server error occurred."}}), 500

@issues_api_bp.route('/api/issues/image-quality-check', methods=['POST'])
@limiter.limit("30 per minute")
@require_auth
def check_image_quality():
    """
    Direct evaluation endpoint for image quality gate and road defect detection.
    Accepts an uploaded image file, returns quality metrics and YOLO detector envelope.
    """
    if 'image' not in request.files:
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": "No image provided."}}), 400
    file = request.files['image']
    if not file or not file.filename:
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": "Empty file."}}), 400

    valid, err_msg = validate_image_file(file)
    if not valid:
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": err_msg}}), 400

    try:
        from services.ai.image_gate import evaluate_image_quality
        from services.ai.road_detector import detect_and_format_defect

        file.seek(0)
        res = evaluate_image_quality(file, user_id=str(g.current_user["_id"]) if hasattr(g, "current_user") and g.current_user else None, db=db)

        file.seek(0)
        det_info = detect_and_format_defect(file)
        file.seek(0)

        return jsonify({
            "success": True,
            "result": res,
            "detector": det_info
        }), 200
    except Exception as e:
        return jsonify({"success": False, "error": {"code": "EVAL_ERROR", "message": str(e)}}), 500

@issues_api_bp.route('/api/issues/<id>/ai-audit', methods=['GET'])
@require_auth
@require_role('officer', 'admin')
def get_issue_ai_audit(id):
    """
    Returns AI decisions and human corrections for an issue.
    Strictly restricted to officer and admin roles.
    """
    try:
        query_id = id
        decisions = list(db.ai_decisions.find({"issue_id": str(query_id)}, {"_id": 0}).sort("created_at", 1))
        corrections = list(db.ai_corrections.find({"issue_id": str(query_id)}, {"_id": 0}).sort("created_at", 1))
        return jsonify({
            "success": True,
            "issue_id": str(query_id),
            "decisions": decisions,
            "corrections": corrections
        }), 200
    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"success": False, "error": {"code": "SERVER_ERROR", "message": "Failed to fetch AI audit trail."}}), 500

@issues_api_bp.route('/api/issues/<id>/repair-evidence', methods=['GET'])
@require_auth
@require_role('officer', 'admin')
def get_issue_repair_evidence(id):
    """
    Returns repair evidence audit records for an issue.
    Strictly restricted to officer and admin roles per Section 4.2.
    """
    try:
        query_id = id
        parsed_id = parse_object_id(id)
        query = {"$or": [{"issue_id": str(query_id)}]}
        if parsed_id:
            query["$or"].append({"issue_id": str(parsed_id)})
        evidence = list(db.repair_evidence.find(query, {"_id": 0}).sort("created_at", -1))
        return jsonify({
            "success": True,
            "issue_id": str(query_id),
            "evidence": evidence
        }), 200
    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"success": False, "error": {"code": "SERVER_ERROR", "message": "Failed to fetch repair evidence."}}), 500

@issues_api_bp.route('/api/issues/<id>/duplicate-suggestions', methods=['GET'])
@require_auth
def get_duplicate_suggestions(id):
    """
    Retrieves suggested duplicate links for a given issue.
    Returns list of candidate issues with similarity breakdown.
    """
    try:
        links = list(db.duplicate_links.find({"source_issue_id": str(id), "status": "suggested"}, {"_id": 0}))
        results = []
        for link in links:
            target_id = link.get("target_issue_id")
            target_issue = None
            if ObjectId.is_valid(target_id):
                target_issue = db.issues.find_one({"_id": ObjectId(target_id)})
            if not target_issue:
                target_issue = db.issues.find_one({"issue_id": target_id})
            if target_issue:
                results.append({
                    "target_issue_id": target_id,
                    "target_title": target_issue.get("title"),
                    "target_description": target_issue.get("description"),
                    "target_category": target_issue.get("category"),
                    "target_status": target_issue.get("status"),
                    "score": link.get("score"),
                    "components": link.get("components", {})
                })
        return jsonify({
            "success": True,
            "suggestions": results,
            "prompt": "Similar report nearby. Is this the same problem?" if results else None
        }), 200
    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"success": False, "error": {"code": "SERVER_ERROR", "message": str(e)}}), 500

@issues_api_bp.route('/api/issues/<id>/duplicate-confirm', methods=['POST'])
@require_auth
@verified_required
@limiter.limit("20 per minute")
def confirm_duplicate_link(id):
    """
    Citizen or officer confirms that issue <id> is a duplicate of target_issue_id.
    Never auto-merges: records confirmed link in duplicate_links and increments
    support/corroboration count on target issue.
    """
    try:
        data = request.get_json(silent=True) or request.form
        target_id = data.get("target_issue_id")
        if not target_id:
            return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": "target_issue_id is required."}}), 400

        user_id = str(g.current_user["_id"])
        
        # Update link status
        db.duplicate_links.update_one(
            {"source_issue_id": str(id), "target_issue_id": str(target_id)},
            {"$set": {"status": "confirmed", "confirmed_by": user_id, "confirmed_at": datetime.utcnow()}},
            upsert=True
        )

        # Increment support on target issue
        filter_target = {"_id": ObjectId(target_id)} if ObjectId.is_valid(target_id) else {"issue_id": target_id}
        db.issues.update_one(
            filter_target,
            {
                "$addToSet": {"supporters": {"user_id": user_id, "confirmed_at": datetime.utcnow().isoformat()}},
                "$inc": {"support_count": 1}
            }
        )

        # Log AI correction audit record
        from services.ai.decision_logger import log_ai_correction
        log_ai_correction(
            db=db,
            issue_id=str(id),
            field_changed="duplicate_link",
            before_value="suggested",
            after_value="confirmed",
            actor_id=user_id,
            actor_role=g.current_user.get("role", "citizen")
        )

        return jsonify({
            "success": True,
            "status": "confirmed",
            "message": "Duplicate link confirmed. Target issue support updated."
        }), 200
    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"success": False, "error": {"code": "SERVER_ERROR", "message": str(e)}}), 500

@issues_api_bp.route('/api/issues/<id>', methods=['GET'])
@require_auth
def get_issue(id):
    try:
        issue = None
        if ObjectId.is_valid(id):
            issue = db.issues.find_one({"_id": ObjectId(id)})
        if not issue:
            issue = db.issues.find_one({"issue_id": id})
            
        if not issue:
            return jsonify({"success": False, "error": {"code": "NOT_FOUND", "message": "Issue not found."}}), 404
            
        authorized, auth_err = authorize_issue_access(g.current_user, issue)
        if not authorized:
            return jsonify(auth_err[0]), auth_err[1]
            
        role = g.current_user.get("role")
        user_id = str(g.current_user["_id"])
        if role in ["officer", "admin"]:
            from utils.serializers import serialize_officer_issue
            issue_data = serialize_officer_issue(issue)
        else:
            from utils.serializers import serialize_citizen_issue
            issue_data = serialize_citizen_issue(issue, user_id=user_id)
        ai_prediction = issue.get("ai_prediction") or issue.get("ai_analysis", {}).get("ai_prediction", {})
        op_classification = issue.get("operational_classification") or {
            "issue_type": issue.get("type"),
            "category": issue.get("category"),
            "severity": issue.get("severity"),
            "department": issue.get("department"),
            "officer_override": issue.get("ai_analysis", {}).get("officer_overridden", False)
        }
        status_hist = issue.get("status_history", [])
        
        cefap_doc = db.cefap_results.find_one({"$or": [{"issue_id": str(issue.get("_id"))}, {"issue_id": issue.get("issue_id")}]}, {"_id": 0})
        signals = {
            "text_severity": issue.get("text_severity") or (cefap_doc.get("text_severity") if cefap_doc else None),
            "image_severity": issue.get("image_severity") or (cefap_doc.get("image_severity") if cefap_doc else None),
            "location_impact": issue.get("location_impact") or (cefap_doc.get("location_impact") if cefap_doc else None),
            "corroboration": issue.get("corroboration") or (cefap_doc.get("corroboration") if cefap_doc else None),
            "recurrence": issue.get("recurrence") or (cefap_doc.get("recurrence") if cefap_doc else None),
            "sla_risk": issue.get("sla_risk") or (cefap_doc.get("sla_risk") if cefap_doc else None),
        }
        evidence_reliability = issue.get("evidence_reliability") or (cefap_doc.get("evidence_reliability") if cefap_doc else None)
        evidence_agreement = issue.get("evidence_agreement") or (cefap_doc.get("evidence_agreement") if cefap_doc else None)
        monsoon_active = issue.get("monsoon_active") if issue.get("monsoon_active") is not None else (cefap_doc.get("monsoon_active", False) if cefap_doc else False)

        issue_data["ai_prediction"] = ai_prediction
        issue_data["operational_classification"] = op_classification
        issue_data["officer_override"] = op_classification.get("officer_override", False)
        issue_data["status_history"] = status_hist
        issue_data["signals"] = signals
        issue_data["evidence_reliability"] = evidence_reliability
        issue_data["evidence_agreement"] = evidence_agreement
        issue_data["monsoon_active"] = monsoon_active
        issue_data["cips_score"] = issue.get("cips_score") or (cefap_doc.get("cips_score") if cefap_doc else None)
        issue_data["ctve_triggered"] = issue.get("ctve_triggered", False)
        issue_data["ctve_message"] = issue.get("ctve_message")

        # Phase 6: Advisory ML priority suggestion (behind AI_ML_PRIORITY_SHADOW)
        if getattr(Config, "AI_ML_PRIORITY_SHADOW", False):
            try:
                from services.ai.priority_ml import predict_priority_ml
                ml_signals = {
                    "text_severity": signals.get("text_severity", 0.5),
                    "image_severity": signals.get("image_severity", 0.0),
                    "location_impact": signals.get("location_impact", 0.4),
                    "corroboration": signals.get("corroboration", 0.0),
                    "recurrence": signals.get("recurrence", 0.0),
                    "sla_risk": signals.get("sla_risk", 0.0),
                    "evidence_reliability": evidence_reliability or 0.5,
                    "disagreement": abs((signals.get("text_severity") or 0.5) - (signals.get("image_severity") or 0.0)),
                    "monsoon_active": monsoon_active or False
                }
                ml_prio_res = predict_priority_ml(ml_signals)
                issue_data["ml_priority_suggestion"] = ml_prio_res["value"]
            except Exception as ml_err:
                current_app.logger.warning(f"[OfficerAPI] ML priority shadow error: {ml_err}")

        # Phase 9: Unified Lifecycle Timeline with Evidence-Level Badges (Rule R7)
        timeline_events = []
        c_at = issue.get("created_at")
        timeline_events.append({
            "stage": "Complaint Intake",
            "actor": "citizen",
            "evidence_level": "verified",
            "timestamp": c_at.isoformat() if isinstance(c_at, datetime) else str(c_at),
            "summary": "Initial report submitted with location and user description."
        })

        ai_decs = list(db.ai_decisions.find({"$or": [{"issue_id": str(issue["_id"])}, {"issue_id": issue.get("issue_id")}]}).sort("created_at", 1))
        for dec in ai_decs:
            res_dict = dec.get("result", {})
            timeline_events.append({
                "stage": dec.get("stage", "ai_analysis").replace("_", " ").title(),
                "actor": res_dict.get("source", "ai_pipeline"),
                "evidence_level": res_dict.get("evidence_level", "inferred"),
                "timestamp": dec.get("created_at").isoformat() if isinstance(dec.get("created_at"), datetime) else str(dec.get("created_at")),
                "summary": f"Completed {dec.get('stage')} evaluation (model: {dec.get('model_version', 'v1')})."
            })

        for sh in status_hist:
            timeline_events.append({
                "stage": f"State: {sh.get('status', '').replace('_', ' ').title()}",
                "actor": "officer" if "officer" in str(sh.get("status", "")).lower() else ("worker" if "worker" in str(sh.get("status", "")).lower() else "system"),
                "evidence_level": "verified",
                "timestamp": str(sh.get("timestamp")),
                "summary": sh.get("notes") or f"Issue status transitioned to {sh.get('status')}."
            })

        issue_data["lifecycle_timeline"] = timeline_events

        res = {
            "success": True,
            "issue_id": issue.get("issue_id") or str(issue["_id"]),
            "status": issue.get("status"),
            "ai_prediction": ai_prediction,
            "operational_classification": op_classification,
            "officer_override": op_classification.get("officer_override", False),
            "priority": issue.get("priority") or issue.get("severity"),
            "status_history": status_hist,
            "lifecycle_timeline": timeline_events,
            "signals": signals,
            "evidence_reliability": evidence_reliability,
            "evidence_agreement": evidence_agreement,
            "monsoon_active": monsoon_active,
            "cips_score": issue_data["cips_score"],
            "ctve_triggered": issue_data["ctve_triggered"],
            "ctve_message": issue_data["ctve_message"],
            "ml_priority_suggestion": issue_data.get("ml_priority_suggestion"),
            "data": issue_data
        }
        return jsonify(res), 200
    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"success": False, "error": {"code": "SERVER_ERROR", "message": "An internal server error occurred."}}), 500

@issues_api_bp.route('/<issue_id>/ctve-response', methods=['POST'])
@issues_api_bp.route('/api/issues/<issue_id>/ctve-response', methods=['POST'])
@require_auth
def ctve_response(issue_id):
    """
    Citizen responds to a CTVE re-verification request.
    Either uploads a new photo or confirms their description is accurate.
    Updates the complaint and clears ctve_triggered flag.
    """
    user_id = str(g.current_user["_id"])

    # Verify ownership
    issue = None
    if ObjectId.is_valid(issue_id):
        issue = db.issues.find_one({"_id": ObjectId(issue_id)})
    if not issue:
        issue = db.issues.find_one({"issue_id": issue_id})

    if not issue:
        return jsonify({"error": "Complaint not found"}), 404

    if str(issue.get("reporter_id") or issue.get("citizen_id")) != user_id and g.current_user.get("role") not in ["admin", "officer"]:
        return jsonify({"error": "Unauthorised"}), 403

    now = datetime.utcnow()
    response_type = request.form.get("ctve_response") or (
        request.get_json(silent=True) or {}
    ).get("ctve_response")

    update = {
        "ctve_triggered": False,
        "ctve_message": None,
        "verification_required": False,
        "ctve_resolved_at": now,
        "ctve_response": response_type,
        "updated_at": now,
    }

    if response_type == "photo_uploaded":
        image_file = request.files.get("photo")
        if image_file:
            from routes.api.issues import validate_image_file
            valid, err_msg = validate_image_file(image_file)
            if not valid:
                return jsonify({"error": err_msg or "Invalid image file"}), 400

            upload_dir = current_app.config.get("UPLOAD_FOLDER", os.path.join(current_app.root_path, "uploads", "issues"))
            os.makedirs(upload_dir, exist_ok=True)
            ext = image_file.filename.rsplit('.', 1)[-1].lower() if '.' in image_file.filename else 'jpg'
            new_filename = f"{uuid.uuid4().hex}.{ext}"
            new_filepath = os.path.join(upload_dir, new_filename)
            image_file.save(new_filepath)
            image_url = f"/files/issues/{new_filename}"

            from services import ai_service
            image_result = ai_service.analyze_complaint_image(new_filepath)

            update["ctve_photo_url"] = image_url
            update["image_severity"] = image_result.get("severity") if isinstance(image_result, dict) else None
            update["image_confidence"] = image_result.get("confidence") if isinstance(image_result, dict) else None

            images = issue.get("images", [])
            images.append({
                "filename": new_filename,
                "filepath": new_filepath,
                "url": image_url,
                "type": "ctve_reverification",
                "uploaded_by": ObjectId(user_id),
                "uploaded_at": now
            })
            update["images"] = images

            from services.cefap_pipeline import cefap_stage
            existing = db.cefap_results.find_one({"$or": [{"issue_id": str(issue["_id"])}, {"issue_id": issue.get("issue_id")}]})
            if existing:
                new_cefap = cefap_stage(db, {
                    "issue_id": str(issue["_id"]),
                    "ward_id": issue.get("ward_id"),
                    "service": issue.get("service") or issue.get("category"),
                    "text_severity": issue.get("severity"),
                    "text_confidence": issue.get("ai_confidence", 0.5),
                    "image_severity": update["image_severity"],
                    "image_confidence": update["image_confidence"],
                    "location_type": issue.get("location_type", "unknown"),
                    "vote_count": issue.get("support_count", 0),
                    "historical_complaints": [],
                    "created_at": issue.get("created_at", now),
                    "sla_deadline": issue.get("sla_deadline"),
                })
                update["cips_score"] = new_cefap["cips"]
                update["priority"] = new_cefap["priority"]
                update["evidence_reliability"] = new_cefap["evidence_reliability"]
                update["evidence_agreement"] = new_cefap["evidence_agreement"]

    db.issues.update_one(
        {"_id": issue["_id"]},
        {
            "$set": update,
            "$push": {
                "status_history": {
                    "status": "CTVE_RESOLVED",
                    "timestamp": now.isoformat(),
                    "actor": "citizen",
                    "note": f"CTVE response: {response_type}",
                }
            },
        }
    )

    db.cefap_ctve_events.update_one(
        {"issue_id": str(issue["_id"])},
        {"$set": {
            "issue_id": str(issue["_id"]),
            "outcome": response_type,
            "outcome_at": now,
            "cips_recalculated": response_type == "photo_uploaded",
            "new_cips_score": update.get("cips_score"),
        }},
        upsert=True
    )

    return jsonify({"message": "Response recorded", "updated_priority": update.get("priority")}), 200

@issues_api_bp.route('/api/issues/<id>/citizen-verify', methods=['POST'])
@require_auth
@verified_required
@require_role('citizen', 'resident')
def citizen_verify_issue(id):
    parsed_id = parse_object_id(id)
    if not parsed_id:
        return jsonify({"success": False, "error": {"code": "NOT_FOUND", "message": "Invalid issue ID format."}}), 404
        
    data = request.get_json() or {}
    resolved = data.get("resolved")
    feedback = data.get("feedback", "")
    
    if resolved is None:
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": "resolved boolean parameter required."}}), 422
        
    try:
        verification_service.citizen_verify(str(parsed_id), str(g.current_user["_id"]), resolved, feedback)
        return jsonify({"success": True, "message": "Resolution status submitted successfully."}), 200
    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"success": False, "error": {"code": "SERVER_ERROR", "message": "An internal server error occurred."}}), 500

@issues_api_bp.route('/api/issues', methods=['GET'])
@issues_api_bp.route('/api/citizen/issues', methods=['GET'])
@require_auth
@verified_required
@require_role('admin', 'officer', 'citizen', 'resident')
def list_issues():
    ward_filter = request.args.get("ward")
    status_filter = request.args.get("status")
    category_filter = request.args.get("category")
    severity_filter = request.args.get("severity")
    q = request.args.get("q")
    
    query = {}
    
    ai_filters = {}
    if q and q.strip() != "":
        from services.ai_service import parse_search_query
        ai_filters = parse_search_query(q)
        
    if "min_age_hours" in ai_filters:
        limit_dt = datetime.utcnow() - timedelta(hours=ai_filters["min_age_hours"])
        query["created_at"] = {"$lte": limit_dt}
        
    user_role = g.current_user.get("role")
    if user_role in ["citizen", "resident"]:
        import hmac
        import hashlib
        user_id_str = str(g.current_user["_id"])
        secret_key = current_app.config.get("SECRET_KEY", "default-salt").encode("utf-8")
        reporter_hash = hmac.new(secret_key, user_id_str.encode("utf-8"), hashlib.sha256).hexdigest()
        anon_docs = list(db.anonymous_reporters.find({"reporter_hash": reporter_hash}, {"issue_id": 1}))
        anon_ids = [d["issue_id"] for d in anon_docs if "issue_id" in d]
        if anon_ids:
            query["$or"] = [{"citizen_id": ObjectId(g.current_user["_id"])}, {"_id": {"$in": anon_ids}}]
        else:
            query["citizen_id"] = ObjectId(g.current_user["_id"])
    else:
        officer_ward = g.current_user.get("ward")
        if officer_ward and str(officer_ward).strip().lower() not in ('all', '*', ''):
            query["ward"] = officer_ward
        elif ward_filter and str(ward_filter).strip().lower() not in ('all', '*', ''):
            query["ward"] = ward_filter
        elif "ward" in ai_filters:
            query["ward"] = ai_filters["ward"]
            
    if status_filter and status_filter != "all":
        statuses = [value.strip() for value in status_filter.split(",") if value.strip()]
        query["status"] = statuses[0] if len(statuses) == 1 else {"$in": statuses}
    elif "status" in ai_filters:
        query["status"] = ai_filters["status"]
        
    if category_filter and category_filter != "all":
        query["category"] = category_filter
    elif "category" in ai_filters:
        query["category"] = ai_filters["category"]
        
    if severity_filter and severity_filter != "all":
        query["severity"] = severity_filter
    elif "severity" in ai_filters:
        query["severity"] = ai_filters["severity"]
        
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 50))
    skip = (page - 1) * per_page
    
    sort_field = request.args.get("sort", "created_at")
    sort_direction = -1 if request.args.get("direction", "desc") != "asc" else 1
    if sort_field not in {"created_at", "updated_at", "priority_score"}:
        sort_field = "created_at"
    raw_issues = list(db.issues.find(query).sort(sort_field, sort_direction).skip(skip).limit(per_page))
    serialized_issues = serialize(raw_issues)
    
    for idx, iss in enumerate(serialized_issues):
        raw_doc = raw_issues[idx]
        imgs = raw_doc.get("images") or []
        img_val = raw_doc.get("image")
        first_url = (img_val.get("url") if isinstance(img_val, dict) else (img_val if isinstance(img_val, str) else None)) or (imgs[0].get("url") if imgs and isinstance(imgs[0], dict) else (imgs[0] if imgs and isinstance(imgs[0], str) else None))
        
        ai_conf = raw_doc.get("ai_prediction", {}).get("confidence") or raw_doc.get("ai_analysis", {}).get("confidence") or 0.85
        
        sla_obj = raw_doc.get("sla") or {}
        sla_deadline = raw_doc.get("sla_deadline")
        sla_breached = sla_obj.get("breached", False)
        if not sla_breached and sla_deadline:
            if isinstance(sla_deadline, datetime):
                sla_breached = sla_deadline < datetime.utcnow()
            elif isinstance(sla_deadline, str):
                try:
                    sla_breached = datetime.fromisoformat(sla_deadline.replace("Z", "+00:00")).replace(tzinfo=None) < datetime.utcnow()
                except Exception:
                    pass

        w_id = raw_doc.get("worker_id") or raw_doc.get("assignment", {}).get("worker_id")
        
        iss["thumbnail_url"] = first_url or "/static/uploads/issues/placeholder.jpg"
        iss["ai_confidence"] = float(ai_conf)
        iss["sla_breached"] = bool(sla_breached)
        iss["department"] = raw_doc.get("department", "roads")
        iss["worker_id"] = str(w_id) if w_id else None
        
        ai_data = raw_doc.get("ai_analysis") or {}
        img_dets = ai_data.get("image_detections") or raw_doc.get("image_detections") or []
        vis_ev = raw_doc.get("visual_evidence") or ai_data.get("visual_evidence") or {}
        if not img_dets and vis_ev.get("defect_name"):
            img_dets = [vis_ev["defect_name"]]
        iss["ai_analysis"] = ai_data
        iss["visual_evidence"] = vis_ev
        iss["image_detections"] = img_dets

        if getattr(Config, "AI_ML_PRIORITY_SHADOW", False):
            try:
                from services.ai.priority_ml import predict_priority_ml
                iss_sig = {
                    "text_severity": raw_doc.get("text_severity", 0.5),
                    "image_severity": raw_doc.get("image_severity", 0.0),
                    "location_impact": raw_doc.get("location_impact", 0.4),
                    "corroboration": raw_doc.get("corroboration", 0.0),
                    "recurrence": raw_doc.get("recurrence", 0.0),
                    "sla_risk": raw_doc.get("sla_risk", 0.0),
                    "evidence_reliability": raw_doc.get("evidence_reliability", 0.5),
                    "disagreement": raw_doc.get("disagreement", 0.0),
                    "monsoon_active": raw_doc.get("monsoon_active", False)
                }
                ml_sugg = predict_priority_ml(iss_sig)
                iss["ml_priority_suggestion"] = ml_sugg["value"]
            except Exception:
                pass
        
    return jsonify({"success": True, "data": serialized_issues, "page": page, "per_page": per_page}), 200

@issues_api_bp.route('/api/issues/<id>/review', methods=['POST'])
@require_auth
@require_role('officer', 'admin')
def review_issue(id):
    parsed_id = parse_object_id(id)
    if not parsed_id:
        return jsonify({"success": False, "error": {"code": "NOT_FOUND", "message": "Invalid issue ID format."}}), 404
        
    issue = db.issues.find_one({"_id": parsed_id})
    if not issue:
        return jsonify({"success": False, "error": {"code": "NOT_FOUND", "message": "Issue not found."}}), 404
        
    authorized, auth_err = authorize_issue_access(g.current_user, issue)
    if not authorized:
        return jsonify(auth_err[0]), auth_err[1]
        
    data = request.get_json() or {}
    category = data.get("category")
    severity = data.get("severity")
    department = data.get("department")
    issue_type = data.get("type")
    reason = data.get("reason", "Officer manual override.")
    
    update_fields = {}
    if category and category in CATEGORIES:
        update_fields["category"] = category
    if severity and severity in SEVERITIES:
        update_fields["severity"] = severity
    if department and department in DEPARTMENTS:
        update_fields["department"] = department
    if issue_type and isinstance(issue_type, str) and 2 <= len(issue_type.strip()) <= 80:
        update_fields["type"] = issue_type.strip()
        
    # Record AI performance evaluation
    ai_analysis = issue.get("ai_analysis", {})
    original_prediction = ai_analysis.get("ai_prediction") or ai_analysis.get("final_prediction") or {
        "category": ai_analysis.get("category"),
        "type": ai_analysis.get("type"),
        "severity": ai_analysis.get("severity"),
        "department": ai_analysis.get("department"),
        "confidence": ai_analysis.get("confidence", 0.0),
        "provider": ai_analysis.get("provider", "unknown")
    }
    ai_prediction = {
        "category": original_prediction.get("category"),
        "type": original_prediction.get("type"),
        "severity": original_prediction.get("severity"),
        "department": original_prediction.get("department"),
        "confidence": original_prediction.get("confidence", 0.0),
        "provider": original_prediction.get("provider", "unknown")
    }
    
    human_decision = {
        "category": category if (category and category in CATEGORIES) else ai_prediction["category"],
        "type": issue_type.strip() if (issue_type and isinstance(issue_type, str)) else ai_prediction.get("type"),
        "severity": severity if (severity and severity in SEVERITIES) else ai_prediction["severity"],
        "department": department if (department and department in DEPARTMENTS) else ai_prediction["department"]
    }
    
    from services.ai_evaluation_service import record_ai_evaluation
    try:
        record_ai_evaluation(
            issue_id=str(parsed_id),
            ai_task="classification",
            ai_prediction=ai_prediction,
            human_decision=human_decision,
            evaluated_by_id=g.current_user["_id"]
        )
    except Exception as eval_err:
        print(f"[AI Evaluation] Error recording evaluation: {eval_err}")

    if update_fields:
        officer_override = {
            key: value for key, value in human_decision.items()
            if value is not None and value != ai_prediction.get(key)
        }
        update_fields["ai_analysis.officer_overridden"] = True
        update_fields["ai_analysis.override_reason"] = reason
        update_fields["ai_analysis.ai_prediction"] = ai_prediction
        update_fields["ai_analysis.officer_override"] = officer_override
        update_fields["ai_analysis.final_operational_value"] = human_decision
        update_fields["updated_at"] = datetime.utcnow()
        update_fields["status"] = "officer_reviewed"
        
        # Log audit paths
        for field, new_val in update_fields.items():
            if field not in ["updated_at", "status"]:
                old_val = issue.get(field)
                if field.startswith("ai_analysis."):
                    old_val = issue.get("ai_analysis", {}).get(field.split(".")[-1])
                log_audit("issue", str(parsed_id), g.current_user["_id"], "OVERRIDE", field, old_val, new_val, reason)
                
        db.issues.update_one({"_id": parsed_id}, {"$set": update_fields})
    else:
        db.issues.update_one({"_id": parsed_id}, {"$set": {"status": "officer_reviewed", "updated_at": datetime.utcnow()}})
        log_audit("issue", str(parsed_id), g.current_user["_id"], "APPROVE_AI", reason="AI auto-classification confirmed by Officer.")
        
    # Recalculate the versioned evidence score from the revised classification.
    updated_issue = db.issues.find_one({"_id": parsed_id})
    new_deadline = sla_service.assign_sla(updated_issue)
    from services.evidence_priority import evaluate_priority
    old_decision = updated_issue.get("priority_decision") or {}
    old_features = old_decision.get("input_features") or {}
    new_decision = evaluate_priority({
        **old_features,
        "severity": updated_issue.get("severity"),
        "image_available": bool(updated_issue.get("images")),
        "location_available": "location" not in (updated_issue.get("missing_evidence") or []),
    })
    
    db.issues.update_one(
        {"_id": parsed_id},
        {"$set": {
            "sla_deadline": new_deadline,
            "priority_score": new_decision["score"],
            "priority_decision": new_decision,
            "priority_model_version": new_decision["model_version"],
            "human_review_required": new_decision["human_review_required"],
            "missing_evidence": new_decision["missing_evidence"],
        }}
    )
        
    return jsonify({"success": True, "message": "AI analysis override successful."}), 200

@issues_api_bp.route('/api/issues/<id>/priority', methods=['POST'])
@require_auth
@require_role('officer', 'admin')
def override_issue_priority(id):
    parsed_id = parse_object_id(id)
    if not parsed_id:
        return jsonify({"success": False, "error": {"code": "NOT_FOUND", "message": "Invalid issue ID format."}}), 404

    issue = db.issues.find_one({"_id": parsed_id})
    if not issue:
        return jsonify({"success": False, "error": {"code": "NOT_FOUND", "message": "Issue not found."}}), 404
        
    authorized, auth_err = authorize_issue_access(g.current_user, issue)
    if not authorized:
        return jsonify(auth_err[0]), auth_err[1]
    officer_ward = g.current_user.get("ward")
    if officer_ward not in [None, "all", "ALL", "*"] and officer_ward != issue.get("ward"):
        return jsonify({"success": False, "error": {"code": "FORBIDDEN", "message": "Access restricted to your assigned ward."}}), 403

    payload = request.get_json(silent=True) or {}
    try:
        score = float(payload.get("score"))
    except (TypeError, ValueError):
        score = -1
    reason = payload.get("reason")
    if not math.isfinite(score) or not 0 <= score <= 100 or not isinstance(reason, str) or len(reason.strip()) < 3:
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": "A score from 0 to 100 and a reason are required."}}), 422

    now = datetime.utcnow()
    decision = issue.get("priority_decision") or {}
    decision["model_score"] = decision.get("model_score", decision.get("score"))
    decision["score"] = round(score, 2)
    decision["priority_tier"] = "P1" if score >= 75 else "P2" if score >= 50 else "P3" if score >= 25 else "P4"
    decision["decision_source"] = "human_override"
    decision["human_override"] = {
        "score": round(score, 2),
        "reason": reason.strip(),
        "officer_id": str(g.current_user["_id"]),
        "overridden_at": now.isoformat(),
    }
    decision["reasons"] = list(decision.get("reasons") or []) + [{
        "code": "human_override",
        "contribution": 0.0,
        "detail": reason.strip(),
    }]
    db.issues.update_one({"_id": parsed_id}, {"$set": {
        "priority_score": round(score, 2),
        "priority_decision": decision,
        "priority_override": decision["human_override"],
        "updated_at": now,
    }})
    log_audit("issue", str(parsed_id), g.current_user["_id"], "PRIORITY_OVERRIDE", "priority_score", issue.get("priority_score"), score, reason.strip())
    return jsonify({"success": True, "priority_score": round(score, 2), "priority_decision": decision}), 200

@issues_api_bp.route('/api/issues/<id>/assign', methods=['POST'])
@require_auth
@require_role('officer', 'admin')
def assign_issue(id):
    parsed_id = parse_object_id(id)
    if not parsed_id:
        return jsonify({"success": False, "error": {"code": "NOT_FOUND", "message": "Invalid issue ID format."}}), 404
        
    data = request.get_json() or {}
    worker_id = data.get("worker_id")
    if not worker_id:
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": "worker_id required."}}), 422
        
    try:
        assignment_service.assign_worker(str(parsed_id), worker_id, str(g.current_user["_id"]))
        return jsonify({"success": True, "message": "Worker assigned successfully."}), 200
    except ValueError as e:
        return jsonify({"success": False, "error": {"code": "INVALID_OPERATION", "message": str(e)}}), 400
    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"success": False, "error": {"code": "SERVER_ERROR", "message": "An internal server error occurred."}}), 500

@issues_api_bp.route('/api/issues/<id>/officer-verify', methods=['POST'])
@require_auth
@require_role('officer', 'admin')
def officer_verify_issue(id):
    parsed_id = parse_object_id(id)
    if not parsed_id:
        return jsonify({"success": False, "error": {"code": "NOT_FOUND", "message": "Invalid issue ID format."}}), 404
        
    data = request.get_json() or {}
    approved = data.get("approved")
    notes = data.get("notes", "")
    
    if approved is None:
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": "approved boolean required."}}), 422
        
    try:
        verification_service.officer_verify(str(parsed_id), str(g.current_user["_id"]), approved, notes)
        return jsonify({"success": True, "message": "Resolution verified successfully."}), 200
    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"success": False, "error": {"code": "SERVER_ERROR", "message": "An internal server error occurred."}}), 500

@issues_api_bp.route('/api/worker/jobs', methods=['GET'])
@require_auth
@require_role('worker')
def list_worker_jobs():
    query = {
        "worker_id": ObjectId(g.current_user["_id"]),
        "status": {"$in": ["assigned", "work_started"]}
    }
    issues = list(db.issues.find(query).sort("priority_score", -1))
    return jsonify({"success": True, "data": serialize(issues)}), 200

@issues_api_bp.route('/api/issues/<id>/start', methods=['POST'])
@require_auth
@require_role('worker')
def start_work(id):
    parsed_id = parse_object_id(id)
    if not parsed_id:
        return jsonify({"success": False, "error": {"code": "NOT_FOUND", "message": "Invalid issue ID format."}}), 404
        
    issue = db.issues.find_one({"_id": parsed_id})
    if not issue:
        return jsonify({"success": False, "error": {"code": "NOT_FOUND", "message": "Issue not found."}}), 404
        
    authorized, auth_err = authorize_issue_access(g.current_user, issue)
    if not authorized:
        return jsonify(auth_err[0]), auth_err[1]
        
    if str(issue.get("worker_id")) != str(g.current_user["_id"]):
        return jsonify({"success": False, "error": {"code": "FORBIDDEN", "message": "Job not assigned to you."}}), 403
        
    try:
        complaint_service.update_status(str(parsed_id), "work_started", str(g.current_user["_id"]))
        return jsonify({"success": True, "message": "Task started successfully."}), 200
    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"success": False, "error": {"code": "SERVER_ERROR", "message": "An internal server error occurred."}}), 500

@issues_api_bp.route('/api/issues/<id>/resolve', methods=['POST'])
@require_auth
@require_role('worker')
def resolve_issue(id):
    parsed_id = parse_object_id(id)
    if not parsed_id:
        return jsonify({"success": False, "error": {"code": "NOT_FOUND", "message": "Invalid issue ID format."}}), 404
        
    issue = db.issues.find_one({"_id": parsed_id})
    if not issue:
        return jsonify({"success": False, "error": {"code": "NOT_FOUND", "message": "Issue not found."}}), 404
        
    authorized, auth_err = authorize_issue_access(g.current_user, issue)
    if not authorized:
        return jsonify(auth_err[0]), auth_err[1]
        
    if str(issue.get("worker_id")) != str(g.current_user["_id"]):
        return jsonify({"success": False, "error": {"code": "FORBIDDEN", "message": "Job not assigned to you."}}), 403
        
    notes = request.form.get("notes", "Resolved by field worker.")
    
    file = request.files.get('after_image') or request.files.get('image')
    if not file or not file.filename:
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": "After resolution photo required."}}), 400
        
    valid, err = validate_image_file(file)
    if not valid:
        return jsonify({"success": False, "error": {"code": "SECURITY_ERROR", "message": err}}), 400
        
    upload_dir = current_app.config.get("RESOLUTION_FOLDER", os.path.join(current_app.root_path, "uploads", "resolution"))
    os.makedirs(upload_dir, exist_ok=True)
    
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else 'jpg'
    filename = f"{uuid.uuid4().hex}.{ext}"
    filepath = os.path.join(upload_dir, filename)
    file.save(filepath)
    
    after_image = {
        "filename": filename,
        "filepath": filepath,
        "url": f"/files/resolution/{filename}"
    }
    
    # Try to find a before image from the issue details
    before_image = {"filepath": ""}
    before_imgs = [img for img in issue.get("images", []) if img.get("type") == "before"]
    if before_imgs:
        before_image["filepath"] = os.path.join(upload_dir, before_imgs[0]["filename"])
        
    try:
        ai_ver = verification_service.submit_resolution(str(parsed_id), str(g.current_user["_id"]), before_image, after_image, notes)
        return jsonify({
            "success": True,
            "message": "Resolution uploaded successfully.",
            "data": ai_ver
        }), 200
    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"success": False, "error": {"code": "SERVER_ERROR", "message": "An internal server error occurred."}}), 500

@issues_api_bp.route('/api/issues/emergency-monitor', methods=['GET'])
@require_auth
def get_emergency_monitor():
    """
    Returns active P0 emergency issues with live SLA countdown calculations.
    P0 SLA limit is 1 hour per master specification.
    """
    now = datetime.utcnow()
    query = {
        "$and": [
            {"$or": [{"priority": "P0"}, {"emergency": True}]},
            {"status": {"$nin": ["closed", "resolved", "rejected"]}}
        ]
    }

    user_role = g.current_user.get("role")
    officer_ward = g.current_user.get("ward")
    if user_role == "officer" and officer_ward not in ["all", "*", None]:
        query["$and"].append({"$or": [{"ward": officer_ward}, {"location.ward": officer_ward}]})

    p0_issues = list(db.issues.find(query).sort("created_at", -1))
    results = []

    for iss in p0_issues:
        c_at = iss.get("created_at") or now
        if isinstance(c_at, str):
            try:
                c_at = datetime.fromisoformat(c_at)
            except Exception:
                c_at = now

        sla_deadline = c_at + timedelta(hours=1)
        remaining_seconds = int((sla_deadline - now).total_seconds())
        is_breached = remaining_seconds <= 0
        urgency_tier = "breached" if is_breached else ("imminent_breach" if remaining_seconds < 900 else "active")

        results.append({
            "issue_id": iss.get("issue_id") or str(iss["_id"]),
            "title": iss.get("title") or iss.get("description", "")[:40],
            "category": iss.get("category"),
            "ward": iss.get("ward"),
            "status": iss.get("status"),
            "priority": "P0",
            "created_at": c_at.isoformat(),
            "sla_deadline": sla_deadline.isoformat(),
            "remaining_seconds": max(0, remaining_seconds),
            "is_breached": is_breached,
            "urgency_tier": urgency_tier
        })

    return jsonify({
        "success": True,
        "active_p0_count": len(results),
        "emergencies": results
    }), 200

@issues_api_bp.route('/api/issues/<id>/declare-emergency', methods=['POST'])
@require_auth
@require_role('citizen', 'officer')
def declare_issue_emergency(id):
    parsed_id = parse_object_id(id)
    if not parsed_id:
        return jsonify({"success": False, "error": {"code": "NOT_FOUND", "message": "Invalid issue ID format."}}), 404
        
    try:
        issue = db.issues.find_one({"_id": parsed_id})
        if not issue:
            return jsonify({"success": False, "error": {"code": "NOT_FOUND", "message": "Issue not found."}}), 404
            
        # Citizen security check
        if g.current_user["role"] == "citizen" and str(issue["citizen_id"]) != str(g.current_user["_id"]):
            return jsonify({"success": False, "error": {"code": "FORBIDDEN", "message": "You can only declare emergency on your own issues."}}), 403
            
        data = request.get_json() or {}
        emergency_category = data.get("emergency_category", "DANGEROUS_INFRASTRUCTURE")
        
        updated = complaint_service.declare_emergency(str(parsed_id), str(g.current_user["_id"]), emergency_category)
        return jsonify({
            "success": True,
            "message": "Emergency successfully declared.",
            "data": serialize(updated)
        }), 200
    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"success": False, "error": {"code": "SERVER_ERROR", "message": "An internal server error occurred."}}), 500

@issues_api_bp.route('/api/issues/<id>/confirm', methods=['POST'])
@require_auth
@verified_required
@require_role('citizen', 'resident')
@limiter.limit("20 per minute")
def confirm_issue(id):
    parsed_id = parse_object_id(id)
    if not parsed_id:
        return jsonify({"success": False, "error": {"code": "NOT_FOUND", "message": "Invalid issue ID format."}}), 404
        
    try:
        data = request.get_json() or {}
        note = data.get("note", "")
        
        new_count = complaint_service.add_community_confirmation(
            issue_id=str(parsed_id),
            citizen_id=str(g.current_user["_id"]),
            note=note
        )
        
        return jsonify({
            "success": True,
            "message": "Community confirmation added successfully.",
            "data": {
                "confirmation_count": new_count
            }
        }), 200
    except ValueError as e:
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": str(e)}}), 400
    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"success": False, "error": {"code": "SERVER_ERROR", "message": "An internal server error occurred."}}), 500

@issues_api_bp.route('/api/issues/<id>/feedback', methods=['POST'])
@require_auth
@verified_required
@require_role('citizen', 'resident')
def post_issue_feedback(id):
    parsed_id = parse_object_id(id)
    if not parsed_id:
        return jsonify({"success": False, "error": {"code": "NOT_FOUND", "message": "Invalid issue ID format."}}), 404
        
    try:
        data = request.get_json() or {}
        rating = data.get("rating")
        feedback_text = data.get("feedback_text", "")
        
        if rating is None:
            return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": "Rating field is required."}}), 422
            
        updated = complaint_service.submit_feedback(
            issue_id=str(parsed_id),
            citizen_id=str(g.current_user["_id"]),
            rating=int(rating),
            feedback_text=feedback_text
        )
        
        return jsonify({
            "success": True,
            "message": "Feedback submitted successfully.",
            "data": serialize(updated)
        }), 200
    except ValueError as e:
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": str(e)}}), 400
    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"success": False, "error": {"code": "SERVER_ERROR", "message": "An internal server error occurred."}}), 500

@issues_api_bp.route('/api/issues/<id>/audit-log', methods=['GET'])
@require_auth
@require_role('officer', 'admin')
def get_issue_audit_log(id):
    parsed_id = parse_object_id(id)
    if not parsed_id:
        return jsonify({"success": False, "error": {"code": "NOT_FOUND", "message": "Invalid issue ID format."}}), 404
        
    try:
        logs = list(db.audit_logs.find({"entity_id": parsed_id}).sort("timestamp", 1))
        data = []
        for log in logs:
            actor = db.users.find_one({"_id": log.get("actor_id")}, {"name": 1, "role": 1})
            actor_name = actor.get("name", "System") if actor else "System"
            if log.get("actor_id") is None and log.get("action") == "AI_REVIEW":
                actor_name = "AI System"
                
            data.append({
                "actor_name": actor_name,
                "action": log.get("action"),
                "field_changed": log.get("field_changed"),
                "old_value": log.get("old_value"),
                "new_value": log.get("new_value"),
                "reason": log.get("reason"),
                "timestamp": log["timestamp"].isoformat() if log.get("timestamp") else None
            })
        return jsonify({"success": True, "data": data}), 200
    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"success": False, "error": {"code": "SERVER_ERROR", "message": "An internal server error occurred."}}), 500


@issues_api_bp.route('/api/issues/<id>/reject', methods=['POST'])
@require_auth
@require_role('officer', 'admin')
def reject_issue(id):
    parsed_id = parse_object_id(id)
    if not parsed_id:
        return jsonify({"success": False, "error": {"code": "NOT_FOUND", "message": "Invalid issue ID format."}}), 404

    issue = db.issues.find_one({"_id": parsed_id})
    if not issue:
        return jsonify({"success": False, "error": {"code": "NOT_FOUND", "message": "Issue not found."}}), 404
        
    authorized, auth_err = authorize_issue_access(g.current_user, issue)
    if not authorized:
        return jsonify(auth_err[0]), auth_err[1]

    # Only reject if in a rejectable state
    if issue.get("status") not in ("submitted", "ai_reviewed", "officer_reviewed"):
        return jsonify({"success": False, "error": {"code": "CONFLICT", "message": "Issue cannot be rejected from its current status."}}), 409

    # Officer ward check
    user_ward = g.current_user.get("ward")
    if str(user_ward or '').strip().lower() not in ('all', '*', '') and issue.get("ward") != user_ward:
        return jsonify({"success": False, "error": {"code": "FORBIDDEN", "message": "Access restricted to your assigned ward."}}), 403

    data = request.get_json() or {}
    reason = data.get("reason", "Rejected by officer.").strip() or "Rejected by officer."

    try:
        db.issues.update_one({"_id": parsed_id}, {"$set": {"rejection_reason": reason}})
        complaint_service.update_status(str(parsed_id), "rejected", str(g.current_user["_id"]), reason=reason)
        return jsonify({"success": True, "message": "Issue rejected successfully."}), 200
    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"success": False, "error": {"code": "SERVER_ERROR", "message": "An internal server error occurred."}}), 500


@issues_api_bp.route('/api/issues/<id>/status', methods=['PATCH', 'POST'])
@require_auth
def update_issue_status_route(id):
    try:
        issue = None
        if ObjectId.is_valid(id):
            issue = db.issues.find_one({"_id": ObjectId(id)})
        if not issue:
            issue = db.issues.find_one({"issue_id": id})
        if not issue:
            return jsonify({"success": False, "error": {"code": "NOT_FOUND", "message": "Issue not found."}}), 404

        authorized, auth_err = authorize_issue_access(g.current_user, issue)
        if not authorized:
            return jsonify(auth_err[0]), auth_err[1]
            
        data = request.get_json() or {}
        new_status = data.get("status")
        if not new_status:
            return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": "status parameter required."}}), 422
            
        updated_issue = complaint_service.update_status(
            str(issue["_id"]), new_status, str(g.current_user["_id"]), actor_role=g.current_user.get("role")
        )
        return jsonify({"success": True, "message": f"Status updated to {new_status}.", "data": serialize(updated_issue)}), 200
    except ValueError as e:
        return jsonify({"success": False, "error": {"code": "ILLEGAL_TRANSITION", "message": str(e)}}), 422
    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"success": False, "error": {"code": "SERVER_ERROR", "message": "An internal server error occurred."}}), 500


@issues_api_bp.route('/api/issues/<id>/classification', methods=['PATCH', 'POST'])
@require_auth
@require_role('officer', 'admin')
def update_issue_classification(id):
    try:
        issue = None
        if ObjectId.is_valid(id):
            issue = db.issues.find_one({"_id": ObjectId(id)})
        if not issue:
            issue = db.issues.find_one({"issue_id": id})
        if not issue:
            return jsonify({"success": False, "error": {"code": "NOT_FOUND", "message": "Issue not found."}}), 404
            
        data = request.get_json() or {}
        cat = data.get("category") or issue.get("category", "road")
        itype = data.get("issue_type") or data.get("type") or issue.get("type", "pothole")
        sev = data.get("severity") or issue.get("severity", "medium")
        dept = data.get("department") or issue.get("department", "roads")
        
        op_class = {
            "category": cat,
            "issue_type": itype,
            "severity": sev,
            "department": dept,
            "officer_override": True,
            "overridden_by": str(g.current_user["_id"]),
            "overridden_at": datetime.utcnow().isoformat()
        }
        
        hours = {"critical": 4, "high": 24, "medium": 72, "low": 168}.get(sev, 72)
        from datetime import timedelta
        new_dl = datetime.utcnow() + timedelta(hours=hours)
        sla_info = {"deadline": new_dl.isoformat(), "breached": False}
        
        db.issues.update_one(
            {"_id": issue["_id"]},
            {"$set": {
                "operational_classification": op_class,
                "category": cat,
                "type": itype,
                "severity": sev,
                "priority": normalize_priority(sev),
                "department": dept,
                "sla": sla_info,
                "sla_deadline": new_dl,
                "updated_at": datetime.utcnow()
            }}
        )

        # Phase 1: log correction to db.ai_corrections
        try:
            from services.ai.decision_logger import log_ai_correction
            actor_id = str(g.current_user["_id"])
            actor_role = g.current_user.get("role", "officer")
            old_cat = issue.get("category")
            old_sev = issue.get("severity")
            old_dept = issue.get("department")
            if cat != old_cat:
                log_ai_correction(db, str(issue["_id"]), "category", old_cat, cat, actor_id, actor_role)
            if sev != old_sev:
                log_ai_correction(db, str(issue["_id"]), "severity", old_sev, sev, actor_id, actor_role)
            if dept != old_dept:
                log_ai_correction(db, str(issue["_id"]), "department", old_dept, dept, actor_id, actor_role)
        except Exception as corr_err:
            current_app.logger.warning(f"Failed to log AI correction: {corr_err}")
        
        updated_doc = db.issues.find_one({"_id": issue["_id"]})
        ai_pred = updated_doc.get("ai_prediction") or updated_doc.get("ai_analysis", {}).get("ai_prediction", {})
        
        return jsonify({
            "success": True,
            "message": "Classification updated.",
            "ai_prediction": ai_pred,
            "operational_classification": op_class,
            "priority": sev,
            "sla": sla_info,
            "data": serialize(updated_doc)
        }), 200
    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"success": False, "error": {"code": "SERVER_ERROR", "message": "An internal server error occurred."}}), 500


@issues_api_bp.route('/api/issues/<id>/recommendations', methods=['GET'])
@require_auth
@require_role('officer', 'admin')
def get_issue_worker_recommendations(id):
    try:
        issue = None
        if ObjectId.is_valid(id):
            issue = db.issues.find_one({"_id": ObjectId(id)})
        if not issue:
            issue = db.issues.find_one({"issue_id": id})
        if not issue:
            return jsonify({"success": False, "error": {"code": "NOT_FOUND", "message": "Issue not found."}}), 404
            
        recs = assignment_service.recommend_workers(issue)
        out_recs = []
        for r in recs:
            w_info = r.get("worker", {})
            out_recs.append({
                "worker_id": w_info.get("id"),
                "name": w_info.get("name"),
                "department": issue.get("department", "roads"),
                "skills": w_info.get("skills", []),
                "distance_meters": int(r.get("distance_km", 0) * 1000),
                "status": "available"
            })
            
        if not out_recs:
            workers = list(db.workers.find({"status": "available"})) + list(db.users.find({"role": "worker", "is_available": True}))
            for w in workers:
                out_recs.append({
                    "worker_id": str(w["_id"]),
                    "name": w.get("name"),
                    "department": w.get("department", "roads"),
                    "skills": w.get("skills", []),
                    "distance_meters": 500,
                    "status": "available"
                })
                
        return jsonify({"success": True, "data": out_recs}), 200
    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"success": False, "error": {"code": "SERVER_ERROR", "message": "An internal server error occurred."}}), 500


@issues_api_bp.route('/api/issues/<id>/assignment', methods=['POST'])
@issues_api_bp.route('/api/issues/<id>/assign', methods=['POST'])
@require_auth
@require_role('officer', 'admin')
def assign_issue_route(id):
    try:
        issue = None
        if ObjectId.is_valid(id):
            issue = db.issues.find_one({"_id": ObjectId(id)})
        if not issue:
            issue = db.issues.find_one({"issue_id": id})
        if not issue:
            return jsonify({"success": False, "error": {"code": "NOT_FOUND", "message": "Issue not found."}}), 404
            
        data = request.get_json() or {}
        worker_id = data.get("worker_id")
        if not worker_id:
            return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": "worker_id required."}}), 422
            
        assignment_service.assign_worker(str(issue["_id"]), worker_id, str(g.current_user["_id"]))
        return jsonify({"success": True, "message": "Worker assigned successfully."}), 200
    except ValueError as e:
        return jsonify({"success": False, "error": {"code": "WORKER_UNAVAILABLE", "message": str(e)}}), 400
    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"success": False, "error": {"code": "SERVER_ERROR", "message": "An internal server error occurred."}}), 500


@issues_api_bp.route('/api/issues/<id>/resolution', methods=['POST'])
@issues_api_bp.route('/api/issues/<id>/resolve', methods=['POST'])
@require_auth
@require_role('worker')
def submit_resolution_proof(id):
    try:
        issue = None
        if ObjectId.is_valid(id):
            issue = db.issues.find_one({"_id": ObjectId(id)})
        if not issue:
            issue = db.issues.find_one({"issue_id": id})
        if not issue:
            return jsonify({"success": False, "error": {"code": "NOT_FOUND", "message": "Issue not found."}}), 404
            
        assigned_w = str(issue.get("worker_id")) if issue.get("worker_id") else str(issue.get("assignment", {}).get("worker_id", ""))
        if assigned_w != str(g.current_user["_id"]):
            return jsonify({"success": False, "error": {"code": "FORBIDDEN", "message": "You are not assigned to this issue."}}), 403
            
        notes = request.form.get("notes") or request.form.get("resolution_notes") or "Repaired successfully."
        
        after_img_url = "/static/uploads/issues/after_default.jpg"
        file = request.files.get('after_image') or request.files.get('image')
        if file and file.filename:
            upload_dir = current_app.config.get("RESOLUTION_FOLDER", os.path.join(current_app.root_path, "uploads", "resolution"))
            os.makedirs(upload_dir, exist_ok=True)
            ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else 'jpg'
            filename = f"{uuid.uuid4().hex}.{ext}"
            filepath = os.path.join(upload_dir, filename)
            file.save(filepath)
            after_img_url = f"/files/resolution/{filename}"
                
        now = datetime.utcnow()
        resolution_data = {
            "worker_id": str(g.current_user["_id"]),
            "after_image": after_img_url,
            "notes": notes,
            "resolved_at": now.isoformat()
        }
        
        db.issues.update_one(
            {"_id": issue["_id"]},
            {"$set": {
                "status": "resolved",
                "resolution": resolution_data,
                "updated_at": now
            }, "$push": {
                "status_history": {"status": "resolved", "timestamp": now.isoformat(), "actor_id": str(g.current_user["_id"])}
            }}
        )
        
        try:
            from services.cefap_pipeline import record_resolution_feedback
            record_resolution_feedback(
                db,
                issue_id=str(issue["_id"]),
                ward_id=issue.get("ward_id", "ward_1"),
                predicted_priority=issue.get("priority", "P2"),
                resolved_at=now,
                created_at=issue.get("created_at", now),
                escalation_level=issue.get("escalation_level", 0),
                officer_overrides=issue.get("officer_overrides", 0),
                citizen_confirmed=False
            )
        except Exception as ex:
            pass
        
        return jsonify({
            "success": True,
            "message": "Resolution proof submitted successfully.",
            "resolution": resolution_data,
            "status": "resolved"
        }), 200
    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"success": False, "error": {"code": "SERVER_ERROR", "message": "An internal server error occurred."}}), 500


# ══════════════════════════════════════════════════════════════════════════════
# SmartCivic v2 Extended Routes
# ══════════════════════════════════════════════════════════════════════════════

@issues_api_bp.route('/api/issues/<id>/clarify', methods=['POST'])
@issues_api_bp.route('/api/complaints/<id>/clarify', methods=['POST'])
@require_auth
def submit_clarification(id):
    issue = parse_object_id(id)
    target = db.issues.find_one({"_id": issue}) if issue else db.issues.find_one({"issue_id": id})
    if not target:
        return jsonify({"success": False, "error": {"code": "NOT_FOUND", "message": "Complaint not found."}}), 404

    data = request.get_json() or {}
    selected_issue_id = data.get("issue_type_id") or data.get("issue_type")
    selected_label = data.get("label", selected_issue_id)

    from services.authority_router import resolve_authority
    auth = resolve_authority(target.get("service", target.get("category")), selected_issue_id, target.get("ward_id"))

    now = datetime.utcnow()
    db.issues.update_one(
        {"_id": target["_id"]},
        {
            "$set": {
                "issue_type": selected_issue_id,
                "type": selected_issue_id,
                "ai_route_decision": "HIGH_CONFIDENCE",
                "verification_status": "ACCEPTED",
                "authority_primary": auth.get("authority_id"),
                "authority_secondary": auth.get("secondary", []),
                "updated_at": now
            },
            "$push": {
                "status_history": {
                    "status": "CLARIFIED",
                    "timestamp": now,
                    "actor": "citizen",
                    "note": f"Citizen selected: {selected_label}"
                }
            }
        }
    )

    return jsonify({
        "success": True,
        "message": "Clarification received",
        "routed_to": auth.get("authority_id")
    }), 200


@issues_api_bp.route('/api/issues/<id>/support', methods=['POST'])
@issues_api_bp.route('/api/complaints/<id>/support', methods=['POST'])
@require_auth
@verified_required
@limiter.limit("20 per minute")
def support_complaint(id):
    user = g.current_user
    user_id = str(user["_id"])

    issue_oid = parse_object_id(id)
    complaint = db.issues.find_one({"_id": issue_oid}) if issue_oid else db.issues.find_one({"issue_id": id})
    if not complaint:
        return jsonify({"success": False, "error": {"code": "NOT_FOUND", "message": "Complaint not found."}}), 404

    # Prevent self-support
    reporter_id = str(complaint.get("citizen_id") or complaint.get("user_id") or complaint.get("reporter_id") or "")
    if reporter_id and reporter_id == user_id:
        return jsonify({"success": False, "error": {"code": "SELF_SUPPORT_FORBIDDEN", "message": "You cannot support your own complaint."}}), 400

    # Prevent duplicate support
    existing = any(str(s.get("user_id")) == user_id for s in complaint.get("supporters", []))
    if existing:
        return jsonify({"success": False, "error": {"code": "DUPLICATE_SUPPORT", "message": "You have already supported this complaint."}}), 409

    support_entry = {
        "user_id": user_id,
        "timestamp": datetime.utcnow(),
        "note": (request.get_json(silent=True) or {}).get("note", "")
    }

    db.issues.update_one(
        {"_id": complaint["_id"]},
        {
            "$push": {"supporters": support_entry},
            "$inc": {"support_count": 1, "confirmation_count": 1}
        }
    )

    # Recompute verification score
    updated = db.issues.find_one({"_id": complaint["_id"]})
    from services.complaint_verifier import compute_confidence_score, determine_verification_status
    new_score = compute_confidence_score(updated)
    new_status = determine_verification_status(new_score, {})

    update_payload = {
        "confidence_score": new_score,
        "verification_status": new_status
    }
    if updated.get("support_count", 0) >= 10 and updated.get("priority") == "P3":
        update_payload["priority"] = "P2"

    db.issues.update_one({"_id": complaint["_id"]}, {"$set": update_payload})

    return jsonify({
        "success": True,
        "message": "Support recorded successfully",
        "support_count": updated.get("support_count", 0) + 1,
        "confidence_score": new_score
    }), 200


@issues_api_bp.route('/api/issues/ward', methods=['GET'])
@issues_api_bp.route('/api/complaints/ward', methods=['GET'])
@require_auth
def get_ward_complaints():
    user = g.current_user
    ward_id = user.get("ward_id") or user.get("ward", "Ward 1")
    
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))
    status_filter = request.args.get("status")

    query = {"$or": [{"ward_id": ward_id}, {"ward": ward_id}]}
    if status_filter:
        query["status"] = status_filter

    total = db.issues.count_documents(query)
    items = list(db.issues.find(query).sort("created_at", -1).skip((page - 1) * per_page).limit(per_page))

    return jsonify({
        "success": True,
        "complaints": serialize(items),
        "issues": serialize(items),
        "total": total,
        "page": page
    }), 200


@issues_api_bp.route('/api/issues/food', methods=['POST'])
@issues_api_bp.route('/api/complaints/food', methods=['POST'])
@require_auth
def submit_food_complaint():
    user = g.current_user
    user_id = str(user["_id"])
    data = request.form.to_dict() if request.form else (request.get_json(silent=True) or {})

    description = data.get("description", "Food safety violation report")
    food_details = {
        "establishment_name": data.get("establishment_name", "Unknown establishment"),
        "establishment_type": data.get("establishment_type", "restaurant"),
        "product_name": data.get("product_name", ""),
        "address": data.get("address", "")
    }

    images = []
    if 'photos' in request.files:
        for f in request.files.getlist("photos"):
            if f and f.filename:
                upload_dir = current_app.config.get("UPLOAD_FOLDER", os.path.join(current_app.root_path, "uploads", "issues"))
                os.makedirs(upload_dir, exist_ok=True)
                ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else 'jpg'
                fn = f"{uuid.uuid4().hex}.{ext}"
                fp = os.path.join(upload_dir, fn)
                f.save(fp)
                images.append({"filename": fn, "url": f"/files/issues/{fn}"})

    now = datetime.utcnow()
    complaint = {
        "title": f"Food Safety: {food_details['establishment_name']}",
        "description": description,
        "category": "sanitation",
        "service": "food_safety",
        "issue_type": data.get("issue_type", "food_safety_hazard"),
        "type": data.get("issue_type", "food_safety_hazard"),
        "severity": "high",
        "priority": "P2",
        "status": "submitted",
        "location": {"type": "Point", "coordinates": [77.5946, 12.9716]},
        "address": food_details["address"] or "Bengaluru",
        "ward": user.get("ward", "Ward 1"),
        "ward_id": user.get("ward_id", "ward_1"),
        "citizen_id": ObjectId(user_id),
        "reporter_id": user_id,
        "food_details": food_details,
        "images": images,
        "photos": [img["url"] for img in images],
        "authority_primary": "FSSAI",
        "verification_status": "PENDING",
        "confidence_score": 0.5,
        "supporters": [],
        "support_count": 0,
        "emergency": False,
        "created_at": now,
        "updated_at": now,
        "status_history": [{"status": "SUBMITTED", "timestamp": now, "actor": "citizen", "note": "Food complaint"}]
    }

    res = db.issues.insert_one(complaint)
    complaint_id = str(res.inserted_id)

    return jsonify({
        "success": True,
        "complaint_id": complaint_id,
        "issue_id": complaint_id,
        "message": "Food complaint submitted successfully. Routed to FSSAI.",
        "authority": "FSSAI",
        "fssai_helpline": "1800-112-100"
    }), 201


@issues_api_bp.route('/api/issues/<id>/assign', methods=['POST'])
@issues_api_bp.route('/api/complaints/<id>/assign', methods=['POST'])
@require_auth
@require_role('officer', 'admin')
def assign_complaint(id):
    issue_oid = parse_object_id(id)
    complaint = db.issues.find_one({"_id": issue_oid}) if issue_oid else db.issues.find_one({"issue_id": id})
    if not complaint:
        return jsonify({"success": False, "error": {"code": "NOT_FOUND", "message": "Complaint not found."}}), 404

    data = request.get_json(silent=True) or {}
    officer_id = data.get("officer_id")

    if not officer_id:
        # Auto-assign available officer
        officer = db.users.find_one({
            "role": "officer",
            "department": complaint.get("authority_primary", "GBA-CORP-ROADS"),
            "officer_available": True,
            "current_workload": {"$lt": 8}
        }, sort=[("current_workload", 1)])
        if not officer:
            officer = db.users.find_one({"role": "officer", "officer_available": True})
        if not officer:
            return jsonify({"success": False, "error": {"code": "NO_OFFICER_AVAILABLE", "message": "No available officer in department/ward."}}), 404
        officer_id = str(officer["_id"])

    now = datetime.utcnow()
    db.issues.update_one(
        {"_id": complaint["_id"]},
        {
            "$set": {
                "assigned_officer_id": officer_id,
                "officer_id": ObjectId(officer_id) if ObjectId.is_valid(officer_id) else officer_id,
                "assigned_at": now,
                "status": "assigned"
            },
            "$push": {
                "status_history": {
                    "status": "ASSIGNED",
                    "timestamp": now,
                    "actor_id": str(g.current_user["_id"]),
                    "note": f"Assigned to officer {officer_id}"
                }
            }
        }
    )

    db.users.update_one({"_id": ObjectId(officer_id) if ObjectId.is_valid(officer_id) else officer_id}, {"$inc": {"current_workload": 1}})

    return jsonify({"success": True, "message": "Assigned successfully", "officer_id": officer_id, "status": "assigned"}), 200


