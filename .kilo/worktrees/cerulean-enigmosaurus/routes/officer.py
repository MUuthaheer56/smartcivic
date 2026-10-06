"""
SmartCivic+ — Officer Dashboard Page Blueprint
"""
from flask import Blueprint, render_template, g, request, redirect, jsonify, session, current_app
from functools import wraps
import jwt
from bson import ObjectId
from app import db

officer_bp = Blueprint('officer', __name__)

def require_officer_page(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = getattr(g, "current_user", None)
        if not user and session.get("user_id"):
            u_id = session.get("user_id")
            if ObjectId.is_valid(u_id):
                user = db.users.find_one({"_id": ObjectId(u_id), "role": {"$in": ["officer", "admin"]}})
                g.current_user = user

        if not user:
            token = request.cookies.get("access_token")
            if token:
                secret = current_app.config.get("JWT_SECRET") or current_app.config.get("JWT_SECRET_KEY")
                try:
                    payload = jwt.decode(token, secret, algorithms=["HS256"])
                    user_id = payload.get("user_id") or payload.get("sub")
                    user = db.users.find_one({"_id": ObjectId(user_id), "role": {"$in": ["officer", "admin"]}})
                    if user:
                        g.current_user = user
                except Exception:
                    pass

        if not user:
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated

@officer_bp.route('/officer/dashboard')
@require_officer_page
def dashboard():
    user = g.current_user
    ward = session.get('ward') or user.get('ward', 'Ward 1')
    
    ward_query = {"$or": [{"ward": ward}, {"location.ward": ward}, {"ward_id": ward.lower().replace(" ", "_")}]}

    total_issues = db.issues.count_documents(ward_query)
    pending_issues = db.issues.count_documents({
        "$and": [
            ward_query,
            {"status": {"$in": ["SUBMITTED", "AI_ANALYZED", "OFFICER_REVIEW", "submitted", "ai_reviewed", "under_review"]}}
        ]
    })
    sla_risk_count = db.issues.count_documents({
        "$and": [
            ward_query,
            {"status": {"$nin": ["RESOLVED", "CLOSED", "resolved", "closed"]}},
            {"$or": [{"sla_risk": True}, {"sla_status": {"$in": ["warning", "urgent", "breached"]}}]}
        ]
    })
    emergency_count = db.issues.count_documents({
        "$and": [
            ward_query,
            {"status": {"$nin": ["RESOLVED", "CLOSED", "resolved", "closed"]}},
            {"$or": [{"severity": {"$in": ["Critical", "critical"]}}, {"emergency": True}]}
        ]
    })

    urgent_issues = list(db.issues.find({
        "$and": [
            ward_query,
            {"severity": {"$in": ["High", "Critical", "high", "critical"]}},
            {"status": {"$nin": ["RESOLVED", "CLOSED", "resolved", "closed"]}}
        ]
    }).sort("created_at", -1).limit(5))
    
    for u in urgent_issues:
        u["_id"] = str(u["_id"])

    p0_count = db.issues.count_documents({"$and": [ward_query, {"priority": "P0"}]})
    p1_count = db.issues.count_documents({"$and": [ward_query, {"priority": "P1"}]})
    p2_count = db.issues.count_documents({"$and": [ward_query, {"priority": "P2"}]})
    p3_count = db.issues.count_documents({"$and": [ward_query, {"priority": "P3"}]})

    return render_template(
        'officer/dashboard.html',
        user=user,
        ward=ward,
        total_issues=total_issues,
        pending_issues=pending_issues,
        sla_risk_count=sla_risk_count,
        emergency_count=emergency_count,
        urgent_issues=urgent_issues,
        priority_breakdown={"P0": p0_count, "P1": p1_count, "P2": p2_count, "P3": p3_count}
    )

@officer_bp.route('/admin/dashboard')
@require_officer_page
def admin_dashboard():
    return dashboard()

@officer_bp.route('/api/officer/assign', methods=['POST'])
@officer_bp.route('/officer/assign', methods=['POST'])
def assign_task():
    user = getattr(g, "current_user", None)
    if not user and session.get("user_id"):
        u_id = session.get("user_id")
        if ObjectId.is_valid(u_id):
            user = db.users.find_one({"_id": ObjectId(u_id), "role": {"$in": ["officer", "admin"]}})

    if not user:
        return jsonify({"error": "Unauthorized"}), 403

    data = request.get_json(silent=True) or request.form.to_dict()
    issue_id = data.get("issue_id")
    worker_id = data.get("worker_id")

    if not issue_id or not worker_id:
        return jsonify({"error": "Missing issue_id or worker_id"}), 400

    from services.assignment_service import assign_worker
    from services.complaint_service import transition_issue_state

    try:
        assign_res = assign_worker(str(issue_id), str(worker_id), str(user["_id"]))
        transition_issue_state(db, str(issue_id), "ASSIGNED", str(user["_id"]), notes=f"Assigned to worker {worker_id}")
        return jsonify({"success": True, "message": "Worker assigned and state updated successfully.", "assignment": assign_res}), 200
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
