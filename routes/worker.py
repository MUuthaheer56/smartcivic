from flask import Blueprint, render_template, g, request, redirect, jsonify, session, current_app
from functools import wraps
import jwt
from bson import ObjectId
from app import db

worker_bp = Blueprint('worker', __name__)

def require_worker_page(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = getattr(g, "current_user", None)
        if not user and session.get("user_id"):
            u_id = session.get("user_id")
            if ObjectId.is_valid(u_id):
                user = db.users.find_one({"_id": ObjectId(u_id), "role": "worker"})
                g.current_user = user

        if not user:
            token = request.cookies.get("access_token")
            if token:
                secret = current_app.config.get("JWT_SECRET") or current_app.config.get("JWT_SECRET_KEY")
                try:
                    payload = jwt.decode(token, secret, algorithms=["HS256"])
                    user_id = payload.get("user_id") or payload.get("sub")
                    user = db.users.find_one({"_id": ObjectId(user_id), "role": "worker"})
                    if user:
                        g.current_user = user
                except Exception:
                    pass

        if not user:
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated

@worker_bp.route('/worker/dashboard')
@require_worker_page
def dashboard():
    user = g.current_user
    worker_id = user["_id"]
    w_str = str(worker_id)
    w_oid = ObjectId(worker_id) if ObjectId.is_valid(w_str) else worker_id

    worker_query = {"$or": [{"assigned_worker_id": w_oid}, {"worker_id": w_oid}, {"worker_id": w_str}]}

    active_tasks = list(db.issues.find({
        "$and": [
            worker_query,
            {"status": {"$in": ["ASSIGNED", "EN_ROUTE", "IN_PROGRESS", "WORK_STARTED", "assigned", "en_route", "in_progress", "work_started"]}}
        ]
    }).sort("created_at", -1))

    for t in active_tasks:
        t["_id"] = str(t["_id"])

    completed_count = db.issues.count_documents({
        "$and": [
            worker_query,
            {"status": {"$in": ["RESOLVED", "CLOSED", "OFFICER_VERIFICATION", "WORK_COMPLETED", "resolved", "closed", "officer_verified", "work_completed"]}}
        ]
    })

    return render_template(
        'worker/dashboard.html',
        user=user,
        active_tasks=active_tasks,
        completed_count=completed_count
    )

@worker_bp.route('/worker/update-status/<issue_id>', methods=['POST'])
@worker_bp.route('/api/worker/update-status/<issue_id>', methods=['POST'])
def update_task_status(issue_id):
    user = getattr(g, "current_user", None)
    if not user and session.get("user_id"):
        u_id = session.get("user_id")
        if ObjectId.is_valid(u_id):
            user = db.users.find_one({"_id": ObjectId(u_id), "role": "worker"})

    if not user:
        return jsonify({"error": "Unauthorized"}), 403

    data = request.form.to_dict() if request.form else (request.get_json(silent=True) or {})
    new_status = data.get("status")

    if not new_status:
        return jsonify({"error": "Missing status parameter"}), 400

    from services.complaint_service import transition_issue_state
    res = transition_issue_state(db, str(issue_id), new_status, str(user["_id"]), notes="Worker updated task progression.")
    
    if res.get("success"):
        return jsonify({"success": True, "new_status": new_status}), 200
        
    return jsonify({"success": False, "error": res.get("error", "Status update failed")}), 400

@worker_bp.route('/worker/manifest.json')
def pwa_manifest():
    from flask import Response
    import json
    manifest_data = {
        "name": "SmartCivic Worker Portal",
        "short_name": "SC Worker",
        "start_url": "/worker/dashboard",
        "display": "standalone",
        "background_color": "#1e293b",
        "theme_color": "#3b82f6",
        "description": "SmartCivic+ Field Crew Offline Portal",
        "orientation": "portrait",
        "icons": []
    }
    return Response(json.dumps(manifest_data), mimetype='application/manifest+json')

@worker_bp.route('/worker/sw.js')
def service_worker():
    from flask import send_from_directory
    import os
    return send_from_directory(os.path.join(current_app.root_path, 'static', 'js'), 'sw.js', mimetype='application/javascript')
