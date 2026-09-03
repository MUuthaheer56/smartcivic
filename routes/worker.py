"""
SmartCivic+ — Worker Dashboard Page Blueprint
"""
from flask import Blueprint, render_template, g, request, redirect, current_app
from functools import wraps
import jwt
from bson import ObjectId
from app import db

worker_bp = Blueprint('worker', __name__)

def require_worker_page(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.cookies.get("access_token")
        if not token:
            return redirect("/login")
        secret = current_app.config.get("JWT_SECRET", "default_secret")
        try:
            payload = jwt.decode(token, secret, algorithms=["HS256"])
            user_id = payload.get("user_id")
            user = db.users.find_one({"_id": ObjectId(user_id), "role": "worker"})
            if not user:
                return redirect("/login")
            g.current_user = user
        except Exception:
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated

@worker_bp.route('/worker/dashboard')
@require_worker_page
def dashboard():
    return render_template('worker/dashboard.html', user=g.current_user)

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
