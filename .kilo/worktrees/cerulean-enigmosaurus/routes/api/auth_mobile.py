"""
SmartCivic+ — Mobile API Authentication Blueprint
Provides /api/auth/login and /api/auth/register for mobile clients (React Native / Expo).
"""
from flask import Blueprint, request, jsonify
from bson import ObjectId
from app import db, limiter
from routes.auth import check_password, generate_tokens, hash_password
from utils.auth_helpers import generate_token

api_mobile_auth_bp = Blueprint('api_mobile_auth', __name__)

@api_mobile_auth_bp.route('/api/auth/login', methods=['POST'])
@api_mobile_auth_bp.route('/auth/login_mobile', methods=['POST'])
@limiter.limit("10 per minute")
def mobile_login():
    data = request.get_json(silent=True) or request.form.to_dict() or {}
    email = (data.get("email") or data.get("username") or "").strip().lower()
    password = data.get("password", "")

    if not email or not password:
        return jsonify({"success": False, "message": "Email/Username and password required"}), 400

    user = db.users.find_one({"$or": [{"email": email}, {"username": email}]})
    if not user or not check_password(password, user.get("password_hash", "")):
        return jsonify({"success": False, "message": "Invalid username or password"}), 401

    role = user.get("role", "citizen")
    ward = user.get("ward", "Ward 1")
    token, refresh_token = generate_tokens(str(user["_id"]), role, ward)

    return jsonify({
        "success": True,
        "token": token,
        "access_token": token,
        "refresh_token": refresh_token,
        "role": role,
        "username": user.get("name") or user.get("email"),
        "user_id": str(user["_id"]),
        "ward": ward
    }), 200
