"""
SmartCivic — Authentication & Verification Helpers
Provides JWT generation, verification, and dual session/Bearer token auth decorators.
"""
import os
import jwt
from datetime import datetime, timedelta
from functools import wraps
from flask import jsonify, g, request, current_app
from bson import ObjectId
from app import db

import os
import uuid
import jwt
from datetime import datetime, timedelta, timezone
from functools import wraps
from flask import jsonify, g, request, current_app
from bson import ObjectId
from app import db

def generate_tokens(user_id, role, ward="Ward 1"):
    """Generates hardened access (30m) and refresh (7d) JWT tokens."""
    secret = (current_app.config.get("JWT_SECRET_KEY") or current_app.config.get("JWT_SECRET")) if current_app else os.getenv("JWT_SECRET_KEY", os.getenv("JWT_SECRET", "default_jwt_secret_smartcivic"))
    if not secret or secret == "default_jwt_secret_smartcivic":
        raise RuntimeError("CRITICAL: Weak or missing JWT secret configured.")

    now = datetime.now(timezone.utc)
    access_payload = {
        "sub": str(user_id),
        "user_id": str(user_id),
        "role": role,
        "ward": ward,
        "type": "access",
        "jti": str(uuid.uuid4()),
        "exp": now + timedelta(minutes=30)
    }
    refresh_payload = {
        "sub": str(user_id),
        "user_id": str(user_id),
        "type": "refresh",
        "jti": str(uuid.uuid4()),
        "exp": now + timedelta(days=7)
    }
    return (
        jwt.encode(access_payload, secret, algorithm="HS256"),
        jwt.encode(refresh_payload, secret, algorithm="HS256")
    )

def generate_token(user_id, role, ward="Ward 1"):
    """Legacy helper returning single access token string."""
    access_token, _ = generate_tokens(user_id, role, ward)
    return access_token

def decode_token(token, expected_type="access"):
    """Decodes JWT and enforces token type verification."""
    secret = (current_app.config.get("JWT_SECRET_KEY") or current_app.config.get("JWT_SECRET")) if current_app else os.getenv("JWT_SECRET_KEY", os.getenv("JWT_SECRET", "default_jwt_secret_smartcivic"))
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        if payload.get("type") and payload.get("type") != expected_type:
            return None, "Invalid token type context."
        payload["sub"] = payload.get("user_id") or payload.get("sub")
        return payload, None
    except jwt.ExpiredSignatureError:
        return None, "Token expired."
    except jwt.InvalidTokenError:
        return None, "Malformed or invalid token."
    except Exception as e:
        return None, str(e)

def verify_jwt_token(token):
    """Verifies and decodes a JWT access token."""
    payload, err = decode_token(token, expected_type="access")
    return payload if not err else None

def dual_auth_required(f):
    """Allows access via either Bearer Token (Mobile) or Cookie (Web)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        from routes.auth import require_auth
        return require_auth(f)(*args, **kwargs)
    return decorated

def verified_required(f):
    """
    Decorator: blocks unverified citizens from submitting complaints.
    Officers and admins bypass this check.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        user = getattr(g, "current_user", None)
        if not user:
            user_id = getattr(g, "user_id", None)
            if user_id:
                try:
                    user = db.users.find_one({"_id": ObjectId(user_id)}, {"verified": 1, "role": 1, "status": 1, "verification_status": 1})
                except Exception:
                    pass

        if not user:
            return jsonify({"error": "Unauthorised", "message": "Authentication required"}), 401

        if user.get("status") == "suspended":
            return jsonify({"error": "Account suspended", "message": "Account suspended. Contact support."}), 403

        role = user.get("role", "citizen")
        is_verified = user.get("verified", False)
        v_status = user.get("verification_status", "pending")
        if role in ["citizen", "resident", "worker"] and (not is_verified or v_status in ["pending", "rejected"]):
            return jsonify({
                "error": "Account not verified (pending verification)",
                "action": "verify_ward",
                "message": "Account pending verification"
            }), 403

        return f(*args, **kwargs)

    return decorated

def officer_required(f):
    """
    Decorator requiring officer or admin role.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        from routes.auth import require_auth, require_role
        return require_auth(require_role('officer', 'admin')(f))(*args, **kwargs)
    return decorated

