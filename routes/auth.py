"""
SmartCivic+ — Authentication & JWT Session Blueprint
Sets secure HttpOnly JWT cookies and manages role decorators.
"""
from flask import Blueprint, request, jsonify, g, make_response, current_app
from functools import wraps
from datetime import datetime, timedelta
import jwt
import bcrypt
from bson import ObjectId
from app import db, limiter
from models.user import create_user_doc, UserRegisterSchema, UserLoginSchema
import os

auth_bp = Blueprint('auth', __name__)

def hash_password(plain_text: str) -> str:
    return bcrypt.hashpw(plain_text.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def check_password(plain_text: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain_text.encode('utf-8'), hashed.encode('utf-8'))
    except Exception:
        return False

def generate_tokens(user_id: str, role: str, ward: str):
    secret = current_app.config.get("JWT_SECRET", "default_secret")
    
    access_expiry = datetime.utcnow() + current_app.config.get("JWT_ACCESS_EXPIRES", timedelta(minutes=30))
    refresh_expiry = datetime.utcnow() + current_app.config.get("JWT_REFRESH_EXPIRES", timedelta(days=7))
    
    access_payload = {
        "user_id": str(user_id),
        "role": role,
        "ward": ward,
        "exp": access_expiry
    }
    
    refresh_payload = {
        "user_id": str(user_id),
        "exp": refresh_expiry
    }
    
    access_token = jwt.encode(access_payload, secret, algorithm="HS256")
    refresh_token = jwt.encode(refresh_payload, secret, algorithm="HS256")
    
    return access_token, refresh_token

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.cookies.get("access_token")
        if not token:
            return jsonify({"success": False, "error": {"code": "UNAUTHORIZED", "message": "Access token cookie missing."}}), 401
            
        secret = current_app.config.get("JWT_SECRET", "default_secret")
        try:
            payload = jwt.decode(token, secret, algorithms=["HS256"])
            user_id = payload.get("user_id")
            user = db.users.find_one({"_id": ObjectId(user_id)})
            if not user:
                return jsonify({"success": False, "error": {"code": "UNAUTHORIZED", "message": "User session expired."}}), 401
                
            g.current_user = user
        except jwt.ExpiredSignatureError:
            return jsonify({"success": False, "error": {"code": "UNAUTHORIZED", "message": "Access token expired."}}), 401
        except Exception:
            return jsonify({"success": False, "error": {"code": "UNAUTHORIZED", "message": "Invalid access token."}}), 401
            
        return f(*args, **kwargs)
    return decorated

def require_role(*roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not hasattr(g, "current_user") or not g.current_user:
                return jsonify({"success": False, "error": {"code": "UNAUTHORIZED", "message": "Auth session context not found."}}), 401
                
            if g.current_user.get("role") not in roles:
                return jsonify({"success": False, "error": {"code": "FORBIDDEN", "message": "Access denied for this user role."}}), 403
                
            return f(*args, **kwargs)
        return decorated
    return decorator

@auth_bp.route('/register', methods=['POST'])
@limiter.limit("5 per minute")
def register():
    data = request.get_json() or {}
    schema = UserRegisterSchema()
    errors = schema.validate(data)
    if errors:
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "fields": errors}}), 422
        
    role = data.get("role", "citizen").lower().strip()
    if role != "citizen":
        return jsonify({
            "success": False,
            "error": {"code": "FORBIDDEN", "message": "Only citizen registration is allowed."}
        }), 403
    data["role"] = "citizen"
        
    email = data["email"].lower().strip()
    if db.users.find_one({"email": email}):
        return jsonify({"success": False, "error": {"code": "ALREADY_EXISTS", "message": "Email already registered."}}), 409
        
    pwd_hash = hash_password(data["password"])
    user_doc = create_user_doc(
        name=data["name"],
        email=email,
        password_hash=pwd_hash,
        role=data["role"],
        ward=data["ward"],
        skills=data.get("skills")
    )
    
    result = db.users.insert_one(user_doc)
    
    return jsonify({
        "success": True,
        "message": "User registered successfully.",
        "data": {
            "user_id": str(result.inserted_id)
        }
    }), 201

@auth_bp.route('/login', methods=['POST'])
@limiter.limit("10 per minute")
def login():
    # Rate limit inside the controller if Flask-Limiter is configured, otherwise fallback
    data = request.get_json() or {}
    schema = UserLoginSchema()
    errors = schema.validate(data)
    if errors:
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "fields": errors}}), 422
        
    email = data["email"].lower().strip()
    user = db.users.find_one({"email": email})
    
    now = datetime.utcnow()
    
    if user:
        # Check lock status
        locked_until = user.get("locked_until")
        if locked_until and locked_until > now:
            return jsonify({"success": False, "error": {"code": "LOCKED", "message": "Account temporarily locked. Please try again in 15 minutes."}}), 403
            
    if not user or not check_password(data["password"], user.get("password_hash", "")):
        from services.logger_service import log_security_event
        if user:
            failed_count = user.get("failed_logins", 0) + 1
            if failed_count >= 10:
                lock_time = now + timedelta(minutes=15)
                db.users.update_one({"_id": user["_id"]}, {"$set": {"failed_logins": 0, "locked_until": lock_time}})
                # Write security audit log
                from models.audit_log import create_audit_log_doc
                db.audit_logs.insert_one(create_audit_log_doc(
                    entity_type="user",
                    entity_id=user["_id"],
                    actor_id=user["_id"],
                    action="ACCOUNT_LOCKOUT",
                    reason="Account locked due to 10 consecutive failed login attempts."
                ))
                log_security_event("account_locked", str(user["_id"]), request.remote_addr, {"email": email})
            else:
                db.users.update_one({"_id": user["_id"]}, {"$set": {"failed_logins": failed_count}})
                log_security_event("failed_login", str(user["_id"]), request.remote_addr, {"email": email, "attempt": failed_count})
        else:
            log_security_event("failed_login", None, request.remote_addr, {"email": email})
        return jsonify({"success": False, "error": {"code": "INVALID_CREDENTIALS", "message": "Invalid email or password."}}), 401
        
    # Reset failed login count on successful login
    db.users.update_one({"_id": user["_id"]}, {"$set": {"failed_logins": 0, "locked_until": None}})
    from services.logger_service import log_security_event
    log_security_event("login", str(user["_id"]), request.remote_addr)
        
    # Update last login
    db.users.update_one({"_id": user["_id"]}, {"$set": {"last_login": datetime.utcnow()}})
    
    # Generate tokens
    access_token, refresh_token = generate_tokens(str(user["_id"]), user["role"], user.get("ward", ""))
    
    response = make_response(jsonify({
        "success": True,
        "message": "Login successful.",
        "data": {
            "user": {
                "id": str(user["_id"]),
                "name": user["name"],
                "role": user["role"],
                "ward": user.get("ward", "")
            }
        }
    }), 200)
    
    # Set cookies
    cookie_secure = current_app.config.get("COOKIE_SECURE", False)
    response.set_cookie("access_token", access_token, httponly=True, secure=cookie_secure, samesite="Lax", max_age=1800)
    response.set_cookie("refresh_token", refresh_token, httponly=True, secure=cookie_secure, samesite="Lax", max_age=7*24*3600)
    
    return response

@auth_bp.route('/refresh', methods=['POST'])
def refresh():
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        return jsonify({"success": False, "error": {"code": "UNAUTHORIZED", "message": "Refresh token cookie missing."}}), 401
        
    secret = current_app.config.get("JWT_SECRET", "default_secret")
    try:
        payload = jwt.decode(refresh_token, secret, algorithms=["HS256"])
        user_id = payload.get("user_id")
        user = db.users.find_one({"_id": ObjectId(user_id)})
        if not user:
            return jsonify({"success": False, "error": {"code": "UNAUTHORIZED", "message": "User session expired."}}), 401
            
        access_token, new_refresh_token = generate_tokens(str(user["_id"]), user["role"], user.get("ward", ""))
        
        cookie_secure = current_app.config.get("COOKIE_SECURE", False)
        response = make_response(jsonify({"success": True}), 200)
        response.set_cookie("access_token", access_token, httponly=True, secure=cookie_secure, samesite="Lax", max_age=1800)
        response.set_cookie("refresh_token", new_refresh_token, httponly=True, secure=cookie_secure, samesite="Lax", max_age=7*24*3600)
        return response
    except Exception:
        return jsonify({"success": False, "error": {"code": "UNAUTHORIZED", "message": "Invalid refresh token."}}), 401

@auth_bp.route('/logout', methods=['POST'])
def logout():
    response = make_response(jsonify({"success": True, "message": "Logged out successfully."}), 200)
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    return response
