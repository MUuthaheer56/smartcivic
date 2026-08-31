"""
SmartCivic+ — Issues API Blueprint
Handles complaint CRUD, uploads with MIME validation, and status updates.
"""
from flask import Blueprint, request, jsonify, g, current_app
from bson import ObjectId
import os
import uuid
import magic
from datetime import datetime
from app import db, limiter
from routes.auth import require_auth, require_role
from models.issue import IssueCreateSchema, CATEGORIES, SEVERITIES, DEPARTMENTS
from services import complaint_service, assignment_service, verification_service, priority_service, sla_service
from services.audit_service import log_audit
from utils import serialize

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
        
    # Validate MIME type
    header = file.read(2048)
    file.seek(0)
    try:
        mime = magic.from_buffer(header, mime=True)
        if mime not in {"image/jpeg", "image/png", "image/webp"}:
            return False, f"Invalid image MIME type: {mime}"
    except Exception as e:
        # Fallback to extension validation if magic fails
        print(f"[Security Check] python-magic exception: {e}")
        
    return True, None

@issues_api_bp.route('/api/issues', methods=['POST'])
@require_auth
@require_role('citizen')
@limiter.limit("10 per hour")
def create_issue():
    # Enforce rate limit (10 per hour per user)
    # Checked and controlled via Flask-Limiter in app.py config
    
    # Process text fields
    title = request.form.get("title")
    description = request.form.get("description")
    category = request.form.get("category")
    issue_type = request.form.get("type")
    lat = request.form.get("lat")
    lng = request.form.get("lng")
    address = request.form.get("address")
    ward = request.form.get("ward")
    
    # Validate with Marshmallow schema
    payload = {
        "title": title,
        "description": description,
        "category": category,
        "type": issue_type,
        "lat": float(lat) if lat else None,
        "lng": float(lng) if lng else None,
        "address": address,
        "ward": ward
    }
    
    schema = IssueCreateSchema()
    errors = schema.validate(payload)
    if errors:
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "fields": errors}}), 422
        
    # Handle image file uploads
    images = []
    if 'image' in request.files:
        file = request.files['image']
        if file and file.filename:
            valid, err = validate_image_file(file)
            if not valid:
                return jsonify({"success": False, "error": {"code": "SECURITY_ERROR", "message": err}}), 400
                
            # Create uploads directory if not existing
            upload_dir = current_app.config.get("UPLOAD_FOLDER", "static/uploads/issues")
            os.makedirs(upload_dir, exist_ok=True)
            
            # Sanitized filename: issue_{issue_id}_{type}_{uuid4().hex[:8]}.jpg
            safe_id = str(uuid.uuid4().hex[:8])
            ext = file.filename.rsplit('.', 1)[-1].lower()
            filename = f"issue_temp_before_{safe_id}.{ext}"
            filepath = os.path.join(upload_dir, filename)
            file.save(filepath)
            
            images.append({
                "filename": filename,
                "url": f"/static/uploads/issues/{filename}",
                "type": "before",
                "uploaded_by": ObjectId(g.current_user["_id"]),
                "uploaded_at": datetime.utcnow()
            })
            
    location = {
        "type": "Point",
        "coordinates": [payload["lng"], payload["lat"]],
        "ward": payload["ward"],
        "address": payload["address"]
    }
    
    try:
        issue = complaint_service.create_complaint(
            citizen_id=str(g.current_user["_id"]),
            title=payload["title"],
            description=payload["description"],
            location=location,
            images=images
        )
        
        # Rename temp image file with actual issue ID
        if images:
            old_filepath = os.path.join(current_app.config["UPLOAD_FOLDER"], images[0]["filename"])
            ext = images[0]["filename"].rsplit('.', 1)[-1].lower()
            new_filename = f"issue_{issue['_id']}_before_{uuid.uuid4().hex[:8]}.{ext}"
            new_filepath = os.path.join(current_app.config["UPLOAD_FOLDER"], new_filename)
            if os.path.exists(old_filepath):
                os.rename(old_filepath, new_filepath)
                
            # Update image ref in issue record
            images[0]["filename"] = new_filename
            images[0]["url"] = f"/static/uploads/issues/{new_filename}"
            db.issues.update_one({"_id": issue["_id"]}, {"$set": {"images": images}})
            
        return jsonify({
            "success": True,
            "message": "Complaint submitted successfully.",
            "data": serialize(issue)
        }), 201
    except Exception as e:
        return jsonify({"success": False, "error": {"code": "SERVER_ERROR", "message": str(e)}}), 500

@issues_api_bp.route('/api/issues/<id>', methods=['GET'])
@require_auth
def get_issue(id):
    try:
        issue = db.issues.find_one({"_id": ObjectId(id)})
        if not issue:
            return jsonify({"success": False, "error": {"code": "NOT_FOUND", "message": "Issue not found."}}), 404
            
        # Citizen security constraint: can only access their own issues
        if g.current_user["role"] == "citizen" and str(issue["citizen_id"]) != str(g.current_user["_id"]):
            return jsonify({"success": False, "error": {"code": "FORBIDDEN", "message": "Access restricted."}}), 403
            
        # Officer security constraint: cannot access other wards
        if g.current_user["role"] == "officer" and g.current_user.get("ward") != "all" and issue.get("ward") != g.current_user.get("ward"):
            return jsonify({"success": False, "error": {"code": "FORBIDDEN", "message": "Access restricted to your assigned ward."}}), 403
            
        # Compile timeline from audit logs
        logs = list(db.audit_logs.find({"entity_id": ObjectId(id)}).sort("timestamp", 1))
        timeline = []
        for log in logs:
            actor = db.users.find_one({"_id": log.get("actor_id")}, {"name": 1, "role": 1})
            timeline.append({
                "action": log["action"],
                "actor_name": actor.get("name", "System") if actor else "System",
                "actor_role": actor.get("role", "system") if actor else "system",
                "reason": log.get("reason", ""),
                "timestamp": log["timestamp"]
            })
            
        issue_data = serialize(issue)
        issue_data["timeline"] = timeline
        return jsonify({"success": True, "data": issue_data}), 200
    except Exception as e:
        return jsonify({"success": False, "error": {"code": "SERVER_ERROR", "message": str(e)}}), 500

@issues_api_bp.route('/api/issues/<id>/citizen-verify', methods=['POST'])
@require_auth
@require_role('citizen')
def citizen_verify_issue(id):
    data = request.get_json() or {}
    resolved = data.get("resolved")
    feedback = data.get("feedback", "")
    
    if resolved is None:
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": "resolved boolean parameter required."}}), 422
        
    try:
        verification_service.citizen_verify(id, str(g.current_user["_id"]), resolved, feedback)
        return jsonify({"success": True, "message": "Resolution status submitted successfully."}), 200
    except Exception as e:
        return jsonify({"success": False, "error": {"code": "SERVER_ERROR", "message": str(e)}}), 500

@issues_api_bp.route('/api/issues', methods=['GET'])
@require_auth
@require_role('officer', 'citizen')
def list_issues():
    ward_filter = request.args.get("ward")
    status_filter = request.args.get("status")
    category_filter = request.args.get("category")
    severity_filter = request.args.get("severity")
    q = request.args.get("q")
    
    query = {}
    
    # 1. Parse natural language query if present
    ai_filters = {}
    if q and q.strip() != "":
        from services.ai_service import parse_search_query
        ai_filters = parse_search_query(q)
        
    # Apply age filters
    if "min_age_hours" in ai_filters:
        from datetime import datetime, timedelta
        limit_dt = datetime.utcnow() - timedelta(hours=ai_filters["min_age_hours"])
        query["created_at"] = {"$lte": limit_dt}
        
    # 2. Security checks per role
    if g.current_user["role"] == "citizen":
        query["citizen_id"] = ObjectId(g.current_user["_id"])
    else: # officer
        officer_ward = g.current_user.get("ward")
        if officer_ward != "all":
            query["ward"] = officer_ward
        elif ward_filter:
            query["ward"] = ward_filter
        elif "ward" in ai_filters:
            query["ward"] = ai_filters["ward"]
            
    # 3. Apply standard filters (explicit overrides AI filters)
    if status_filter:
        query["status"] = status_filter
    elif "status" in ai_filters:
        query["status"] = ai_filters["status"]
        
    if category_filter:
        query["category"] = category_filter
    elif "category" in ai_filters:
        query["category"] = ai_filters["category"]
        
    if severity_filter:
        query["severity"] = severity_filter
    elif "severity" in ai_filters:
        query["severity"] = ai_filters["severity"]
        
    # Sorted by priority_score descending with pagination
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))
    skip = (page - 1) * per_page
    
    issues = list(db.issues.find(query).sort("priority_score", -1).skip(skip).limit(per_page))
    return jsonify({"success": True, "data": serialize(issues), "page": page, "per_page": per_page}), 200

@issues_api_bp.route('/api/issues/<id>/review', methods=['POST'])
@require_auth
@require_role('officer')
def review_issue(id):
    issue = db.issues.find_one({"_id": ObjectId(id)})
    if not issue:
        return jsonify({"success": False, "error": {"code": "NOT_FOUND", "message": "Issue not found."}}), 404
        
    data = request.get_json() or {}
    category = data.get("category")
    severity = data.get("severity")
    department = data.get("department")
    reason = data.get("reason", "Officer manual override.")
    
    update_fields = {}
    if category and category in CATEGORIES:
        update_fields["category"] = category
    if severity and severity in SEVERITIES:
        update_fields["severity"] = severity
    if department and department in DEPARTMENTS:
        update_fields["department"] = department
        
    # Record AI performance evaluation
    ai_analysis = issue.get("ai_analysis", {})
    ai_prediction = {
        "category": ai_analysis.get("category"),
        "severity": ai_analysis.get("severity"),
        "department": ai_analysis.get("department"),
        "confidence": ai_analysis.get("confidence", 1.0),
        "provider": ai_analysis.get("provider", "gemini")
    }
    
    human_decision = {
        "category": category if (category and category in CATEGORIES) else ai_prediction["category"],
        "severity": severity if (severity and severity in SEVERITIES) else ai_prediction["severity"],
        "department": department if (department and department in DEPARTMENTS) else ai_prediction["department"]
    }
    
    from services.ai_evaluation_service import record_ai_evaluation
    try:
        record_ai_evaluation(
            issue_id=id,
            ai_task="classification",
            ai_prediction=ai_prediction,
            human_decision=human_decision,
            evaluated_by_id=g.current_user["_id"]
        )
    except Exception as eval_err:
        print(f"[AI Evaluation] Error recording evaluation: {eval_err}")

    if update_fields:
        update_fields["ai_analysis.officer_overridden"] = True
        update_fields["ai_analysis.override_reason"] = reason
        update_fields["updated_at"] = datetime.utcnow()
        update_fields["status"] = "officer_reviewed"
        
        # Log audit paths
        for field, new_val in update_fields.items():
            if field not in ["updated_at", "status"]:
                old_val = issue.get(field)
                if field.startswith("ai_analysis."):
                    old_val = issue.get("ai_analysis", {}).get(field.split(".")[-1])
                log_audit("issue", id, g.current_user["_id"], "OVERRIDE", field, old_val, new_val, reason)
                
        db.issues.update_one({"_id": ObjectId(id)}, {"$set": update_fields})
    else:
        db.issues.update_one({"_id": ObjectId(id)}, {"$set": {"status": "officer_reviewed", "updated_at": datetime.utcnow()}})
        log_audit("issue", id, g.current_user["_id"], "APPROVE_AI", reason="AI auto-classification confirmed by Officer.")
        
    # Recalculate priority & SLA target
    updated_issue = db.issues.find_one({"_id": ObjectId(id)})
    new_deadline = sla_service.assign_sla(updated_issue)
    new_priority = priority_service.calculate_priority(updated_issue, db)
    
    db.issues.update_one(
        {"_id": ObjectId(id)},
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
    data = request.get_json() or {}
    worker_id = data.get("worker_id")
    if not worker_id:
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": "worker_id required."}}), 422
        
    try:
        assignment_service.assign_worker(id, worker_id, str(g.current_user["_id"]))
        return jsonify({"success": True, "message": "Worker assigned successfully."}), 200
    except Exception as e:
        return jsonify({"success": False, "error": {"code": "SERVER_ERROR", "message": str(e)}}), 500

@issues_api_bp.route('/api/issues/<id>/officer-verify', methods=['POST'])
@require_auth
@require_role('officer')
def officer_verify_issue(id):
    data = request.get_json() or {}
    approved = data.get("approved")
    notes = data.get("notes", "")
    
    if approved is None:
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": "approved boolean required."}}), 422
        
    try:
        verification_service.officer_verify(id, str(g.current_user["_id"]), approved, notes)
        return jsonify({"success": True, "message": "Resolution verified successfully."}), 200
    except Exception as e:
        return jsonify({"success": False, "error": {"code": "SERVER_ERROR", "message": str(e)}}), 500

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
    issue = db.issues.find_one({"_id": ObjectId(id)})
    if not issue:
        return jsonify({"success": False, "error": {"code": "NOT_FOUND", "message": "Issue not found."}}), 404
        
    if str(issue.get("worker_id")) != str(g.current_user["_id"]):
        return jsonify({"success": False, "error": {"code": "FORBIDDEN", "message": "Job not assigned to you."}}), 403
        
    try:
        complaint_service.update_status(id, "work_started", str(g.current_user["_id"]))
        return jsonify({"success": True, "message": "Task started successfully."}), 200
    except Exception as e:
        return jsonify({"success": False, "error": {"code": "SERVER_ERROR", "message": str(e)}}), 500

@issues_api_bp.route('/api/issues/<id>/resolve', methods=['POST'])
@require_auth
@require_role('worker')
def resolve_issue(id):
    issue = db.issues.find_one({"_id": ObjectId(id)})
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
    filename = f"issue_{id}_after_{safe_uid}.{ext}"
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
        ai_ver = verification_service.submit_resolution(id, str(g.current_user["_id"]), before_image, after_image, notes)
        return jsonify({
            "success": True,
            "message": "Resolution uploaded successfully.",
            "data": ai_ver
        }), 200
    except Exception as e:
        return jsonify({"success": False, "error": {"code": "SERVER_ERROR", "message": str(e)}}), 500

@issues_api_bp.route('/api/issues/<id>/declare-emergency', methods=['POST'])
@require_auth
@require_role('citizen', 'officer')
def declare_issue_emergency(id):
    try:
        issue = db.issues.find_one({"_id": ObjectId(id)})
        if not issue:
            return jsonify({"success": False, "error": {"code": "NOT_FOUND", "message": "Issue not found."}}), 404
            
        # Citizen security check
        if g.current_user["role"] == "citizen" and str(issue["citizen_id"]) != str(g.current_user["_id"]):
            return jsonify({"success": False, "error": {"code": "FORBIDDEN", "message": "You can only declare emergency on your own issues."}}), 403
            
        data = request.get_json() or {}
        emergency_category = data.get("emergency_category", "DANGEROUS_INFRASTRUCTURE")
        
        updated = complaint_service.declare_emergency(id, str(g.current_user["_id"]), emergency_category)
        return jsonify({
            "success": True,
            "message": "Emergency successfully declared.",
            "data": serialize(updated)
        }), 200
    except Exception as e:
        return jsonify({"success": False, "error": {"code": "SERVER_ERROR", "message": str(e)}}), 500

@issues_api_bp.route('/api/issues/<id>/confirm', methods=['POST'])
@require_auth
@require_role('citizen')
def confirm_issue(id):
    try:
        data = request.get_json() or {}
        note = data.get("note", "")
        
        new_count = complaint_service.add_community_confirmation(
            issue_id=id,
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
        return jsonify({"success": False, "error": {"code": "SERVER_ERROR", "message": str(e)}}), 500

@issues_api_bp.route('/api/issues/<id>/feedback', methods=['POST'])
@require_auth
@require_role('citizen')
def post_issue_feedback(id):
    try:
        data = request.get_json() or {}
        rating = data.get("rating")
        feedback_text = data.get("feedback_text", "")
        
        if rating is None:
            return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": "Rating field is required."}}), 422
            
        updated = complaint_service.submit_feedback(
            issue_id=id,
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
        return jsonify({"success": False, "error": {"code": "SERVER_ERROR", "message": str(e)}}), 500

@issues_api_bp.route('/api/issues/<id>/audit-log', methods=['GET'])
@require_auth
@require_role('officer')
def get_issue_audit_log(id):
    try:
        logs = list(db.audit_logs.find({"entity_id": ObjectId(id)}).sort("timestamp", 1))
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
        return jsonify({"success": False, "error": {"code": "SERVER_ERROR", "message": str(e)}}), 500
