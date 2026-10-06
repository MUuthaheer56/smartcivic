"""
SmartCivic+ — Authentication & JWT Session Blueprint
Sets secure HttpOnly JWT cookies and manages role decorators.
"""
from flask import Blueprint, request, jsonify, g, make_response, current_app, session, render_template, redirect, url_for, flash
from functools import wraps
from datetime import datetime, timedelta, timezone
import jwt
import bcrypt
import hmac
from bson import ObjectId
from pymongo.errors import DuplicateKeyError, PyMongoError
from app import db, limiter
from models.user import create_user_doc, UserRegisterSchema, UserLoginSchema
import os
import uuid

auth_bp = Blueprint('auth', __name__)


def hash_password(plain_text: str) -> str:
    return bcrypt.hashpw(plain_text.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def check_password(plain_text: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain_text.encode('utf-8'), hashed.encode('utf-8'))
    except Exception:
        return False

def generate_tokens(user_id: str, role: str, ward: str):
    secret = (current_app.config.get("JWT_SECRET_KEY") or current_app.config.get("JWT_SECRET")) if current_app else os.getenv("JWT_SECRET_KEY", os.getenv("JWT_SECRET", "default_jwt_secret_smartcivic"))
    if not secret or secret == "default_jwt_secret_smartcivic":
        raise RuntimeError("CRITICAL: Weak or missing JWT secret configured.")

    now = datetime.now(timezone.utc)
    access_expiry = now + timedelta(minutes=30)
    refresh_expiry = now + timedelta(days=7)

    access_payload = {
        "sub": str(user_id),
        "user_id": str(user_id),
        "role": role,
        "ward": ward,
        "type": "access",
        "jti": str(uuid.uuid4()),
        "exp": access_expiry
    }

    refresh_payload = {
        "sub": str(user_id),
        "user_id": str(user_id),
        "type": "refresh",
        "jti": str(uuid.uuid4()),
        "exp": refresh_expiry
    }

    access_token = jwt.encode(access_payload, secret, algorithm="HS256")
    refresh_token = jwt.encode(refresh_payload, secret, algorithm="HS256")

    return access_token, refresh_token

def decode_token(token: str, secret: str = None, expected_type: str = "access") -> dict:
    if not secret:
        secret = (current_app.config.get("JWT_SECRET_KEY") or current_app.config.get("JWT_SECRET")) if current_app else os.getenv("JWT_SECRET_KEY", os.getenv("JWT_SECRET", "default_jwt_secret_smartcivic"))
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        if payload.get("type") and payload.get("type") != expected_type:
            return {}
        payload["sub"] = payload.get("user_id") or payload.get("sub")
        return payload
    except Exception:
        return {}

def require_auth(f):
    @wraps(f)
    def auth_wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization")
        token = None
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split("Bearer ")[1].strip()
        elif "Authorization" not in request.headers:
            token = request.cookies.get("access_token")

        if not token:
            return jsonify({"success": False, "error": {"code": "UNAUTHORIZED", "message": "Access token missing."}}), 401

        secret = (current_app.config.get("JWT_SECRET_KEY") or current_app.config.get("JWT_SECRET")) if current_app else os.getenv("JWT_SECRET_KEY", os.getenv("JWT_SECRET", "default_jwt_secret_smartcivic"))
        try:
            payload = jwt.decode(token, secret, algorithms=["HS256"])
            if payload.get("type") and payload.get("type") != "access":
                return jsonify({"success": False, "error": {"code": "UNAUTHORIZED", "message": "Invalid token type context."}}), 401
            user_id = payload.get("user_id") or payload.get("sub")
            if not user_id or not ObjectId.is_valid(str(user_id)):
                return jsonify({"success": False, "error": {"code": "UNAUTHORIZED", "message": "Invalid user token ID."}}), 401
            user = db.users.find_one({"_id": ObjectId(user_id)})
            if not user:
                return jsonify({"success": False, "error": {"code": "UNAUTHORIZED", "message": "User session expired."}}), 401
            if user.get("status") == "suspended":
                return jsonify({"success": False, "error": {"code": "FORBIDDEN", "message": "Account suspended. Contact support."}}), 403

            g.current_user = user
        except jwt.ExpiredSignatureError:
            return jsonify({"success": False, "error": {"code": "UNAUTHORIZED", "message": "Access token expired."}}), 401
        except Exception:
            return jsonify({"success": False, "error": {"code": "UNAUTHORIZED", "message": "Invalid access token."}}), 401

        return f(*args, **kwargs)
    return auth_wrapper

def require_role(*roles):
    def decorator(f):
        @wraps(f)
        def role_wrapper(*args, **kwargs):
            if not hasattr(g, "current_user") or not g.current_user:
                return jsonify({"success": False, "error": {"code": "UNAUTHORIZED", "message": "Auth session context not found."}}), 401

            user_role = g.current_user.get("role")
            allowed = set(roles)
            if "resident" in allowed: allowed.add("citizen")
            if "citizen" in allowed: allowed.add("resident")

            if user_role not in allowed:
                return jsonify({"success": False, "error": {"code": "FORBIDDEN", "message": "Access denied for this user role."}}), 403

            return f(*args, **kwargs)
        return role_wrapper
    return decorator

@auth_bp.route('/register', methods=['POST'])
@limiter.limit("3 per minute")
def register():
    data = request.form.to_dict() if request.form else (request.get_json(silent=True) or {})
    schema = UserRegisterSchema()
    errors = schema.validate(data)
    if errors:
        first_field = list(errors.keys())[0]
        first_err_list = errors[first_field]
        first_msg = first_err_list[0] if isinstance(first_err_list, list) and first_err_list else str(first_err_list)
        error_message = f"{first_field.capitalize()}: {first_msg}"
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": error_message, "fields": errors}}), 422

    role = data.get("role", "resident").lower().strip()
    ward = data.get("ward") or "Ward 1"

    if role in ["officer", "worker"]:
        expected_code = os.environ.get("ADMIN_INVITE_CODE") or (current_app.config.get("ADMIN_INVITE_CODE") if current_app else None)
        invite_code = data.get("invite_code")
        if not expected_code or not invite_code or not hmac.compare_digest(str(invite_code).strip(), str(expected_code).strip()):
            return jsonify({"error": "Unauthorized staff registration.", "success": False, "message": "Unauthorized staff registration."}), 403
    elif role not in ["resident", "citizen"]:
        role = "resident"

    if role != "admin" and ward == "all":
        return jsonify({"error": "Global scope assignment prohibited during registration.", "success": False, "message": "Global scope assignment prohibited during registration."}), 400

    data["role"] = role
        
    email = data["email"].lower().strip()
    if db.users.find_one({"email": email}):
        return jsonify({"success": False, "error": {"code": "ALREADY_EXISTS", "message": "Email already registered."}}), 409
        
    pwd_hash = hash_password(data["password"])
    user_doc = create_user_doc(
        name=data["name"],
        email=email,
        password_hash=pwd_hash,
        role=data["role"],
        ward=ward,
        skills=data.get("skills") if isinstance(data.get("skills"), list) else None
    )

    # Force unverified state & pending status for new resident/worker accounts
    if data["role"] in ["resident", "citizen", "worker"]:
        user_doc["verified"] = False
        user_doc["verification_status"] = "pending"
        user_doc["status"] = "pending_verification"

    # Handle verification_doc upload if provided
    if 'verification_doc' in request.files:
        doc_file = request.files['verification_doc']
        if doc_file and doc_file.filename:
            doc_ext = doc_file.filename.rsplit('.', 1)[-1].lower() if '.' in doc_file.filename else ''
            if doc_ext not in {'jpg', 'jpeg', 'png', 'webp', 'pdf'}:
                return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": "Unsupported file type for verification document. Allowed: JPG, PNG, WEBP, PDF."}}), 400
            
            if doc_ext == 'pdf':
                header = doc_file.read(10)
                doc_file.seek(0)
                if not header.startswith(b'%PDF-'):
                    return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": "Invalid PDF document content."}}), 400

            upload_dir = os.path.join(current_app.config.get("UPLOAD_FOLDER", "static/uploads"), "verification_docs")
            os.makedirs(upload_dir, exist_ok=True)
            doc_name = f"doc_{uuid.uuid4().hex[:12]}.{doc_ext}"
            saved_path = os.path.join(upload_dir, doc_name)
            doc_file.save(saved_path)
            user_doc["verification_doc"] = f"/static/uploads/verification_docs/{doc_name}"

    try:
        result = db.users.insert_one(user_doc)
    except DuplicateKeyError:
        return jsonify({"success": False, "error": {"code": "ALREADY_EXISTS", "message": "An account with this email address or identifier already exists."}}), 409
    except PyMongoError as db_err:
        return jsonify({"success": False, "error": {"code": "DATABASE_ERROR", "message": f"Database storage error: {str(db_err)}"}}), 500
    except Exception as exc:
        return jsonify({"success": False, "error": {"code": "REGISTRATION_FAILED", "message": f"Registration failed: {str(exc)}"}}), 500
    
    return jsonify({
        "success": True,
        "message": "User registered successfully. Pending verification.",
        "access_token": None,
        "user_id": str(result.inserted_id),
        "data": {
            "user_id": str(result.inserted_id),
            "verified": False,
            "verification_status": "pending"
        }
    }), 201


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def login():
    if request.method == 'GET':
        return render_template('auth/login.html')

    data = request.form.to_dict() if request.form else (request.get_json(silent=True) or {})
    schema = UserLoginSchema()
    errors = schema.validate(data)
    if errors and not request.form:
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "fields": errors}}), 422
        
    email = data.get("email", "").lower().strip()
    pw = data.get("password", "")
    
    if not email or not pw:
        if request.form:
            flash("Email and password are required.", "danger")
            return render_template('auth/login.html'), 400
        return jsonify({"error": "Email and password are required", "message": "Email and password are required"}), 400

    user = db.users.find_one({"email": email})
    now = datetime.utcnow()
    
    if user:
        locked_until = user.get("locked_until")
        if locked_until and locked_until > now:
            msg = "Account temporarily locked. Please try again in 15 minutes."
            if request.form:
                flash(msg, "danger")
                return render_template('auth/login.html'), 403
            return jsonify({"success": False, "error": {"code": "LOCKED", "message": msg}}), 403
            
    if not user or not check_password(pw, user.get("password_hash", "")):
        from services.logger_service import log_security_event
        if user:
            failed_count = user.get("failed_logins", 0) + 1
            if failed_count >= 10:
                lock_time = now + timedelta(minutes=15)
                db.users.update_one({"_id": user["_id"]}, {"$set": {"failed_logins": 0, "locked_until": lock_time}})
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
            
        if request.form:
            flash("Invalid email or password", "danger")
            return render_template('auth/login.html'), 401
        return jsonify({"success": False, "error": {"code": "INVALID_CREDENTIALS", "message": "Invalid email or password."}}), 401
        
    if user.get("status") == "suspended":
        msg = "Account suspended. Contact support."
        if request.form:
            flash(msg, "danger")
            return render_template('auth/login.html'), 403
        return jsonify({"error": msg, "message": msg}), 403

    db.users.update_one({"_id": user["_id"]}, {"$set": {"failed_logins": 0, "locked_until": None, "last_login": datetime.utcnow()}})
    from services.logger_service import log_security_event
    log_security_event("login", str(user["_id"]), request.remote_addr)
    
    access_token, refresh_token = generate_tokens(str(user["_id"]), user["role"], user.get("ward", ""))
    
    user_id_str = str(user["_id"])
    raw_role = user.get("role", "citizen")
    user_role = raw_role.lower()
    canonical_role = "citizen" if user_role in ["resident", "citizen"] else user_role
    verified_flag = user.get("verified", False)
    
    # Store in session for web requests
    session['user_id'] = user_id_str
    session['role'] = canonical_role
    session['ward'] = user.get("ward")
    session['verified'] = verified_flag

    user_info = {
        "id": user_id_str,
        "name": user.get("name"),
        "email": user.get("email"),
        "role": raw_role,
        "verified": verified_flag,
        "verification_status": user.get("verification_status", "approved" if verified_flag else "pending"),
        "ward": user.get("ward"),
        "ward_id": user.get("ward_id"),
        "tier": user.get("tier", "reporter"),
        "status": user.get("status", "pending_verification" if canonical_role == "citizen" else "active")
    }

    # Strict Role-Based Redirection
    if canonical_role == "admin":
        redirect_url = "/admin/dashboard"
    elif canonical_role == "officer":
        redirect_url = "/officer/dashboard"
    elif canonical_role == "worker":
        if not user.get("approved_by_authority", verified_flag):
            flash("Your worker account is pending authority approval.", "warning")
            redirect_url = "/pending-verification"
        else:
            redirect_url = "/worker/dashboard"
    elif not verified_flag:
        redirect_url = "/citizen/verify-ward"
    else:
        redirect_url = "/citizen/dashboard"

    if request.form:
        return redirect(redirect_url)

    response_data = {
        "success": True,
        "message": "Login successful.",
        "redirect": redirect_url,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "role": user_role,
        "user_id": user_id_str,
        "user": user_info,
        "data": {
            "redirect": redirect_url,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "user": user_info
        }
    }

    response = make_response(jsonify(response_data), 200)
    cookie_secure = current_app.config.get("COOKIE_SECURE", False)
    response.set_cookie("access_token", access_token, httponly=True, secure=cookie_secure, samesite="Lax", max_age=1800)
    response.set_cookie("refresh_token", refresh_token, httponly=True, secure=cookie_secure, samesite="Lax", max_age=7*24*3600)
    return response

@auth_bp.route('/refresh', methods=['POST'])
def refresh():
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        return jsonify({"success": False, "error": {"code": "UNAUTHORIZED", "message": "Refresh token cookie missing."}}), 401
        
    secret = current_app.config["JWT_SECRET"]
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

@auth_bp.route('/me', methods=['GET'])
@require_auth
def get_me():
    user = g.current_user
    user_info = {
        "id": str(user["_id"]),
        "user_id": str(user["_id"]),
        "name": user.get("name"),
        "email": user.get("email"),
        "role": user.get("role", "citizen"),
        "verified": user.get("verified", False),
        "ward": user.get("ward"),
        "ward_id": user.get("ward_id"),
        "tier": user.get("tier", "reporter"),
        "civic_score": user.get("civic_score", 0),
        "status": user.get("status", "pending_verification")
    }
    return jsonify({
        "success": True,
        **user_info,
        "data": user_info
    }), 200

@auth_bp.route('/verify-ward', methods=['GET', 'POST'])
@auth_bp.route('/register/verify-area', methods=['GET', 'POST'])
def verify_ward():
    if 'user_id' not in session and not getattr(g, 'current_user', None):
        if request.method == 'GET':
            return redirect(url_for('auth.login'))
            
    user = getattr(g, 'current_user', None)
    if not user and 'user_id' in session:
        user = db.users.find_one({"_id": ObjectId(session['user_id'])})
        g.current_user = user

    if not user:
        if request.method == 'GET':
            return redirect(url_for('auth.login'))
        return jsonify({"success": False, "error": {"code": "UNAUTHORIZED", "message": "Authentication required"}}), 401

    if request.method == 'GET':
        return render_template('auth/verify_ward.html')

    user_id = str(user["_id"])
    data = request.form.to_dict() if request.form else (request.get_json(silent=True) or {})
    area_code = str(data.get("area_code", "") or data.get("ward_code", "")).strip().upper()

    if not area_code:
        if request.form:
            flash("Please provide a valid ward code.", "danger")
            return render_template('auth/verify_ward.html'), 400
        return jsonify({"error": "Area code is required", "message": "Area code is required"}), 400

    ward = db.ward_registry.find_one({
        "$or": [
            {"area_code": area_code},
            {"ward_id": area_code.lower()},
            {"ward_name": area_code}
        ]
    })
    if not ward:
        ward = db.ward_registry.find_one({"area_code": area_code})
    if not ward:
        ward_id = area_code.lower().replace(" ", "_")
        ward_name = area_code
    else:
        ward_id = ward.get("ward_id", "ward_1")
        ward_name = ward.get("ward_name", user.get("ward", "Ward 1"))

    # Resident ward code verification verifies citizen account
    db.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {
            "verified": True,
            "verification_status": "approved",
            "status": "active",
            "ward": ward_name,
            "ward_id": ward_id,
            "area_code": area_code,
            "verification_method": "area_code",
            "verified_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }}
    )
    
    session['verified'] = True
    session['ward'] = ward_name

    if request.form:
        flash('Ward verified successfully!', 'success')
        return redirect(url_for('citizen.dashboard'))

    return jsonify({
        "success": True,
        "message": "Ward verified successfully!",
        "ward_id": ward_id,
        "ward_name": ward_name,
        "verified": True
    }), 200

@auth_bp.route('/verification-status', methods=['GET'])
@require_auth
def verification_status():
    user = g.current_user
    return jsonify({
        "verified": user.get("verified", False),
        "verification_status": user.get("verification_status", "pending"),
        "status": user.get("status", "pending_verification"),
        "ward_id": user.get("ward_id"),
        "tier": user.get("tier", "reporter"),
        "civic_score": user.get("civic_score", 0)
    }), 200

@auth_bp.route('/users/pending', methods=['GET'])
@auth_bp.route('/residents/pending', methods=['GET'])
@require_auth
def list_pending_users():
    current = g.current_user
    if current.get("role") not in ["admin", "officer"]:
        return jsonify({"success": False, "error": {"code": "FORBIDDEN", "message": "Admin/Officer access required."}}), 403

    role_filter = request.args.get("role")
    if role_filter and role_filter in ["citizen", "resident", "worker"]:
        if role_filter in ["citizen", "resident"]:
            role_query = {"$in": ["resident", "citizen"]}
        else:
            role_query = "worker"
    else:
        role_query = {"$in": ["resident", "citizen", "worker"]}

    query = {
        "role": role_query,
        "$or": [
            {"verification_status": {"$in": ["pending", "rejected"]}},
            {"status": {"$in": ["pending_verification", "rejected"]}},
            {"verified": False}
        ]
    }

    pending_users = list(db.users.find(query, {"password_hash": 0}).sort("created_at", -1))
    for user in pending_users:
        user["_id"] = str(user["_id"])
        user.setdefault("verified", False)
        user.setdefault("verification_status", "pending")
        user.setdefault("status", "pending_verification")
        user.setdefault("ward", "Ward 1")

    return jsonify({
        "success": True,
        "count": len(pending_users),
        "data": pending_users,
        "users": pending_users,
        "message": "Pending resident verification queue loaded."
    }), 200

@auth_bp.route('/users/<user_id>/approve', methods=['POST'])
@auth_bp.route('/users/<user_id>/verify', methods=['POST'])
@auth_bp.route('/users/<user_id>/reject', methods=['POST'])
@require_auth
def manual_verify_user(user_id):
    current = g.current_user
    if current.get("role") not in ["admin", "officer"]:
        return jsonify({"success": False, "error": {"code": "FORBIDDEN", "message": "Admin/Officer access required."}}), 403

    data = request.get_json(silent=True) or {}
    action = str(data.get("action", "approve")).lower()
    status_choice = str(data.get("status", "approved")).lower()
    reason = data.get("reason", "Verification rejected by officer")

    if request.path.endswith('/reject') or action == "reject" or status_choice == "rejected":
        db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {
                "verified": False,
                "verification_status": "rejected",
                "status": "rejected",
                "rejection_reason": reason,
                "updated_at": datetime.utcnow()
            }}
        )
        return jsonify({"success": True, "message": "User verification rejected by admin/officer."}), 200

    ward_id = data.get("ward_id", "ward_1")
    db.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {
            "verified": True,
            "verification_status": "approved",
            "status": "active",
            "ward_id": ward_id,
            "verification_method": "admin_manual",
            "verified_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }}
    )
    return jsonify({"success": True, "message": "User verified successfully by admin/officer"}), 200


