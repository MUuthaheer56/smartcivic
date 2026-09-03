"""
SmartCivic+ — Citizen Dashboard Page Blueprint
"""
from flask import Blueprint, render_template, g, request, redirect, current_app
from functools import wraps
import jwt
from bson import ObjectId
from app import db
from routes.auth import require_auth

citizen_bp = Blueprint('citizen', __name__)

def require_citizen_page(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.cookies.get("access_token")
        if not token:
            return redirect("/login")
        secret = current_app.config.get("JWT_SECRET", "default_secret")
        try:
            payload = jwt.decode(token, secret, algorithms=["HS256"])
            user_id = payload.get("user_id")
            user = db.users.find_one({"_id": ObjectId(user_id), "role": "citizen"})
            if not user:
                return redirect("/login")
            g.current_user = user
        except Exception:
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated

@citizen_bp.route('/citizen/dashboard')
@require_citizen_page
def dashboard():
    return render_template('citizen/dashboard.html', user=g.current_user)

@citizen_bp.route('/report')
@citizen_bp.route('/citizen/report')
@require_citizen_page
def report_issue_page():
    return render_template('report_issue.html', user=g.current_user)
