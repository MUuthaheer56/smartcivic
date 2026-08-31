"""
SmartCivic+ — Officer Dashboard Page Blueprint
"""
from flask import Blueprint, render_template, g, request, redirect, current_app
from functools import wraps
import jwt
from bson import ObjectId
from app import db

officer_bp = Blueprint('officer', __name__)

def require_officer_page(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.cookies.get("access_token")
        if not token:
            return redirect("/login")
        secret = current_app.config.get("JWT_SECRET", "default_secret")
        try:
            payload = jwt.decode(token, secret, algorithms=["HS256"])
            user_id = payload.get("user_id")
            user = db.users.find_one({"_id": ObjectId(user_id), "role": "officer"})
            if not user:
                return redirect("/login")
            g.current_user = user
        except Exception:
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated

@officer_bp.route('/officer/dashboard')
@require_officer_page
def dashboard():
    return render_template('officer/dashboard.html', user=g.current_user)
