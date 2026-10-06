"""
SmartCivic+ — Issues API Blueprint
Handles complaint CRUD, uploads with MIME validation, and status updates.
"""
from flask import Blueprint, request, jsonify, g, current_app
from bson import ObjectId
import os
import uuid
try:
    import magic
except Exception:
    magic = None
from datetime import datetime, timedelta
from app import db, limiter
from routes.auth import require_auth, require_role
from utils.auth_helpers import verified_required
from models.issue import IssueCreateSchema, CATEGORIES, SEVERITIES, DEPARTMENTS
from services import complaint_service, assignment_service, verification_service, priority_service, sla_service
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
    description = request.form.get("description") or (request.json.get("description") if request.is_json else None)
    if not description or len(description.strip()) < 10:
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": "description must be at least 10 characters."}}), 400
        
    lat_val = request.form.get("latitude") or request.form.get("lat") or (request.json.get("latitude") or request.json.get("lat") if request.is_json else None)
    lng_val = request.form.get("longitude") or request.form.get("lng") or (request.json.get("longitude") or request.json.get("lng") if request.is_json else None)
    
    try:
        lat = float(lat_val) if lat_val is not None else 12.9716
        lng = float(lng_val) if lng_val is not None else 77.5946
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": "Invalid latitude or longitude."}}), 400

    address = request.form.get("address") or (request.json.get("address") if request.is_json else "MG Road, Bengaluru")
    title = request.form.get("title") or (request.json.get("title") if request.is_json else (description[:40] + "..."))
    category = request.form.get("category") or (request.json.get("category") if request.is_json else "road")
    issue_type = request.form.get("type") or (request.json.get("type") if request.is_json else "pothole")
    ward = request.form.get("ward") or (request.json.get("ward") if request.is_json else "Ward 1")
    citizen_ward = g.current_user.get("ward")
    if citizen_ward and citizen_ward != "all":
        ward = citizen_ward
    
    images = []
    if 'image' in request.files:
        file = request.files['image']
        if file and file.filename:
            upload_dir = current_app.config.get("UPLOAD_FOLDER", "static/uploads/issues")
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
        "address": address
    }
    
    try:
        issue = complaint_service.create_complaint(
            citizen_id=str(g.current_user["_id"]),
            title=title,
            description=description,
            location=location,
            images=images
        )
        
        if images:
            old_filepath = os.path.join(current_app.config["UPLOAD_FOLDER"], images[0]["filename"])
            ext = images[0]["filename"].rsplit('.', 1)[-1].lower()
            new_filename = f"issue_{issue['_id']}_before_{uuid.uuid4().hex[:8]}.{ext}"
            new_filepath = os.path.join(current_app.config["UPLOAD_FOLDER"], new_filename)
            if os.path.exists(old_filepath):
                os.rename(old_filepath, new_filepath)
                
            images[0]["filename"] = new_filename
            images[0]["filepath"] = new_filepath
            images[0]["url"] = f"/static/uploads/issues/{new_filename}"
            db.issues.update_one({"_id": issue["_id"]}, {"$set": {
                "images": images,
                "image": {"url": images[0]["url"], "filename": new_filename}
            }})
            issue["image"] = {"url": images[0]["url"], "filename": new_filename}
            
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
        res_data = serialize(issue)
        res_data["signals"] = signals
        return jsonify({
            "success": True,
            "message": "Complaint submitted successfully.",
            "issue_id": issue.get("issue_id") or str(issue["_id"]),
            "status": issue.get("status", "submitted"),
            "ai_prediction": issue.get("ai_prediction", {}),
            "duplicate": issue.get("duplicate", {"is_duplicate": False}),
            "priority": issue.get("priority", "medium"),
            "cips_score": issue.get("cips_score"),
            "evidence_reliability": issue.get("evidence_reliability"),
            "evidence_agreement": issue.get("evidence_agreement"),
            "ctve_triggered": issue.get("ctve_triggered", False),
            "ctve_message": issue.get("ctve_message"),
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
            
        user_role = g.current_user.get("role")
        if user_role in ["resident", "citizen"] and str(issue.get("citizen_id")) != str(g.current_user["_id"]):
            return jsonify({"success": False, "error": {"code": "FORBIDDEN", "message": "Access restricted to your own issues."}}), 403
            
        if user_role == "officer" and g.current_user.get("ward") not in ["all", "ALL", "*"]:
            user_ward_raw = (g.current_user.get("ward") or "").strip().lower()
            issue_ward_raw = (issue.get("ward") or "").strip().lower()
            user_ward_id = (g.current_user.get("ward_id") or user_ward_raw).strip().lower()
            issue_ward_id = (issue.get("ward_id") or issue_ward_raw).strip().lower()
            ward_match = (user_ward_id == issue_ward_id) or (user_ward_raw == issue_ward_raw) or (user_ward_id in ["all", "*"])
            if not ward_match:
                return jsonify({"success": False, "error": {"code": "FORBIDDEN", "message": "Access restricted to your assigned ward."}}), 403

            
        issue_data = serialize(issue)
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

        res = {
            "success": True,
            "issue_id": issue.get("issue_id") or str(issue["_id"]),
            "status": issue.get("status"),
            "ai_prediction": ai_prediction,
            "operational_classification": op_classification,
            "officer_override": op_classification.get("officer_override", False),
            "priority": issue.get("priority") or issue.get("severity"),
            "status_history": status_hist,
            "signals": signals,
            "evidence_reliability": evidence_reliability,
            "evidence_agreement": evidence_agreement,
            "monsoon_active": monsoon_active,
            "cips_score": issue_data["cips_score"],
            "ctve_triggered": issue_data["ctve_triggered"],
            "ctve_message": issue_data["ctve_message"],
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

            upload_dir = current_app.config.get("UPLOAD_FOLDER", "static/uploads/issues")
            os.makedirs(upload_dir, exist_ok=True)
            ext = image_file.filename.rsplit('.', 1)[-1].lower() if '.' in image_file.filename else 'jpg'
            new_filename = f"issue_{issue['_id']}_ctve_{uuid.uuid4().hex[:8]}.{ext}"
            new_filepath = os.path.join(upload_dir, new_filename)
            image_file.save(new_filepath)
            image_url = f"/static/uploads/issues/{new_filename}"

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
@require_role('citizen')
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
@require_role('officer', 'citizen', 'resident')
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
        query["citizen_id"] = ObjectId(g.current_user["_id"])
    else:
        officer_ward = g.current_user.get("ward")
        if officer_ward and officer_ward != "all":
            query["ward"] = officer_ward
        elif ward_filter and ward_filter != "all":
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
        first_url = raw_doc.get("image", {}).get("url") or (imgs[0].get("url") if imgs else None)
        
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
        
    return jsonify({"success": True, "data": serialized_issues, "page": page, "per_page": per_page}), 200

@issues_api_bp.route('/api/issues/<id>/review', methods=['POST'])
@require_auth
@require_role('officer')
def review_issue(id):
    parsed_id = parse_object_id(id)
    if not parsed_id:
        return jsonify({"success": False, "error": {"code": "NOT_FOUND", "message": "Invalid issue ID format."}}), 404
        
    issue = db.issues.find_one({"_id": parsed_id})
    if not issue:
        return jsonify({"success": False, "error": {"code": "NOT_FOUND", "message": "Issue not found."}}), 404
        
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
        
    # Recalculate priority & SLA target
    updated_issue = db.issues.find_one({"_id": parsed_id})
    new_deadline = sla_service.assign_sla(updated_issue)
    new_priority = priority_service.calculate_priority(updated_issue, db)
    
    db.issues.update_one(
        {"_id": parsed_id},
        {"$set": {
            "sla_deadline": new_deadline,
            "priority_score": new_priority
        }}
    )
        
    return jsonify({"success": True, "message": "AI analysis override successful."}), 200

@issues_api_bp.route('/api/issues/<id>/assign', methods=['POST'])
@require_auth
@require_role('officer')
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
    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"success": False, "error": {"code": "SERVER_ERROR", "message": "An internal server error occurred."}}), 500

@issues_api_bp.route('/api/issues/<id>/officer-verify', methods=['POST'])
@require_auth
@require_role('officer')
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
        
    if str(issue.get("worker_id")) != str(g.current_user["_id"]):
        return jsonify({"success": False, "error": {"code": "FORBIDDEN", "message": "Job not assigned to you."}}), 403
        
    notes = request.form.get("notes", "Resolved by field worker.")
    
    if 'image' not in request.files:
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": "After resolution photo required."}}), 400
        
    file = request.files['image']
    if not file or not file.filename:
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": "Invalid photo upload file."}}), 400
        
    valid, err = validate_image_file(file)
    if not valid:
        return jsonify({"success": False, "error": {"code": "SECURITY_ERROR", "message": err}}), 400
        
    upload_dir = current_app.config.get("UPLOAD_FOLDER", "static/uploads/issues")
    os.makedirs(upload_dir, exist_ok=True)
    
    safe_uid = uuid.uuid4().hex[:8]
    ext = file.filename.rsplit('.', 1)[-1].lower()
    filename = f"issue_{parsed_id}_after_{safe_uid}.{ext}"
    filepath = os.path.join(upload_dir, filename)
    file.save(filepath)
    
    after_image = {
        "filename": filename,
        "filepath": filepath,
        "url": f"/static/uploads/issues/{filename}"
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
@require_role('citizen')
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
@require_role('citizen')
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
@require_role('officer')
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
@require_role('officer')
def reject_issue(id):
    parsed_id = parse_object_id(id)
    if not parsed_id:
        return jsonify({"success": False, "error": {"code": "NOT_FOUND", "message": "Invalid issue ID format."}}), 404

    issue = db.issues.find_one({"_id": parsed_id})
    if not issue:
        return jsonify({"success": False, "error": {"code": "NOT_FOUND", "message": "Issue not found."}}), 404

    # Only reject if in a rejectable state
    if issue.get("status") not in ("submitted", "ai_reviewed", "officer_reviewed"):
        return jsonify({"success": False, "error": {"code": "CONFLICT", "message": "Issue cannot be rejected from its current status."}}), 409

    # Officer ward check
    if g.current_user.get("ward") != "all" and issue.get("ward") != g.current_user.get("ward"):
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
            
        data = request.get_json() or {}
        new_status = data.get("status")
        if not new_status:
            return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": "status parameter required."}}), 422
            
        updated_issue = complaint_service.update_status(str(issue["_id"]), new_status, str(g.current_user["_id"]))
        return jsonify({"success": True, "message": f"Status updated to {new_status}.", "data": serialize(updated_issue)}), 200
    except ValueError as e:
        return jsonify({"success": False, "error": {"code": "ILLEGAL_TRANSITION", "message": str(e)}}), 422
    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"success": False, "error": {"code": "SERVER_ERROR", "message": "An internal server error occurred."}}), 500


@issues_api_bp.route('/api/issues/<id>/classification', methods=['PATCH', 'POST'])
@require_auth
@require_role('officer')
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
                "priority": sev,
                "department": dept,
                "sla": sla_info,
                "sla_deadline": new_dl,
                "updated_at": datetime.utcnow()
            }}
        )
        
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
@require_role('officer')
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
@require_role('officer')
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
        if 'after_image' in request.files:
            file = request.files['after_image']
            if file and file.filename:
                upload_dir = current_app.config.get("UPLOAD_FOLDER", "static/uploads/issues")
                os.makedirs(upload_dir, exist_ok=True)
                ext = file.filename.rsplit('.', 1)[-1].lower()
                filename = f"issue_{issue['_id']}_after_{uuid.uuid4().hex[:8]}.{ext}"
                filepath = os.path.join(upload_dir, filename)
                file.save(filepath)
                after_img_url = f"/static/uploads/issues/{filename}"
                
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
                "ai_route_decision": "AUTO_ROUTE",
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
def support_complaint(id):
    user = g.current_user
    user_id = str(user["_id"])

    issue_oid = parse_object_id(id)
    complaint = db.issues.find_one({"_id": issue_oid}) if issue_oid else db.issues.find_one({"issue_id": id})
    if not complaint:
        return jsonify({"success": False, "error": {"code": "NOT_FOUND", "message": "Complaint not found."}}), 404

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
                upload_dir = current_app.config.get("UPLOAD_FOLDER", "static/uploads/issues")
                os.makedirs(upload_dir, exist_ok=True)
                ext = f.filename.rsplit('.', 1)[-1].lower()
                fn = f"food_{uuid.uuid4().hex[:8]}.{ext}"
                fp = os.path.join(upload_dir, fn)
                f.save(fp)
                images.append({"filename": fn, "url": f"/static/uploads/issues/{fn}"})

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


