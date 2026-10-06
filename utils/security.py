import uuid
import jwt
import os
import re
import logging
from datetime import datetime, timedelta, timezone
from flask import current_app, request, abort
from bson import ObjectId

from utils.validators import (
    allowed_image_file,
    sanitize_text_input,
    validate_complaint_payload,
    ALLOWED_EXTENSIONS,
    MAX_FILE_SIZE_BYTES
)

logger = logging.getLogger(__name__)


# Allowed status transitions matrix (Role -> From Status -> Allowed To Status)
STATUS_TRANSITION_MATRIX = {
    "citizen": {
        "submitted": ["cancelled", "closed"],
        "citizen_verification": ["closed", "reopened"],
        "resolved": ["closed", "reopened"],
        "work_completed": ["closed", "reopened"]
    },
    "worker": {
        "assigned": ["en_route", "work_started", "in_progress", "work_completed", "resolved"],
        "en_route": ["work_started", "in_progress", "work_completed", "resolved"],
        "work_started": ["in_progress", "work_completed", "resolved"],
        "in_progress": ["work_completed", "resolved"]
    },
    "officer": {
        "submitted": ["under_review", "ai_reviewed", "officer_reviewed", "verified", "assigned", "rejected", "duplicate"],
        "ai_reviewed": ["under_review", "officer_reviewed", "verified", "assigned", "rejected", "duplicate"],
        "under_review": ["verified", "officer_reviewed", "assigned", "rejected", "duplicate"],
        "officer_reviewed": ["verified", "assigned", "rejected", "duplicate"],
        "verified": ["assigned", "rejected"],
        "assigned": ["en_route", "work_started", "in_progress", "rejected"],
        "en_route": ["work_started", "in_progress", "work_completed", "resolved"],
        "work_started": ["in_progress", "work_completed", "resolved"],
        "in_progress": ["work_completed", "resolved"],
        "work_completed": ["resolved", "officer_verified", "closed"],
        "resolved": ["officer_verified", "closed", "reopened"],
        "officer_verified": ["citizen_verification", "closed"],
        "citizen_verification": ["closed", "reopened"],
        "reopened": ["assigned", "rejected"],
        "duplicate": ["under_review", "officer_reviewed", "rejected"]
    },
    "admin": {
        "submitted": ["under_review", "assigned", "rejected", "closed", "duplicate"],
        "under_review": ["assigned", "rejected", "closed", "duplicate"],
        "assigned": ["in_progress", "resolved", "rejected", "closed"],
        "in_progress": ["resolved", "rejected", "closed"],
        "work_completed": ["resolved", "officer_verified", "closed"],
        "resolved": ["officer_verified", "closed", "reopened"],
        "officer_verified": ["closed"],
        "citizen_verification": ["closed", "reopened"],
        "reopened": ["assigned", "rejected", "closed"],
        "closed": ["reopened"]
    }
}

def generate_tokens(user_id, role, ward):
    secret = (current_app.config.get("JWT_SECRET_KEY") or current_app.config.get("JWT_SECRET")) if current_app else None
    if not secret or secret == "default_jwt_secret_smartcivic":
        raise RuntimeError("CRITICAL: Unsafe or default JWT secret configuration detected.")
        
    now = datetime.now(timezone.utc)
    access_payload = {
        "sub": str(user_id),
        "sub_id": str(user_id),
        "user_id": str(user_id),
        "role": role,
        "ward": ward,
        "type": "access",
        "jti": str(uuid.uuid4()),
        "exp": now + timedelta(minutes=30)
    }
    refresh_payload = {
        "sub": str(user_id),
        "sub_id": str(user_id),
        "user_id": str(user_id),
        "type": "refresh",
        "jti": str(uuid.uuid4()),
        "exp": now + timedelta(days=7)
    }
    return (
        jwt.encode(access_payload, secret, algorithm="HS256"),
        jwt.encode(refresh_payload, secret, algorithm="HS256")
    )

def decode_token(token, expected_type="access"):
    secret = (current_app.config.get("JWT_SECRET_KEY") or current_app.config.get("JWT_SECRET")) if current_app else None
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        if payload.get("type") and payload.get("type") != expected_type:
            return None, "Invalid token type context."
        payload["sub"] = payload.get("user_id") or payload.get("sub_id") or payload.get("sub")
        return payload, None
    except jwt.ExpiredSignatureError:
        return None, "Token expired."
    except jwt.InvalidTokenError:
        return None, "Malformed or invalid token."
    except Exception as e:
        return None, str(e)

def validate_object_id(val):
    if not val:
        return None
    val_str = str(val)
    if not ObjectId.is_valid(val_str):
        abort(400, description="Invalid identifier format.")
    return ObjectId(val_str)

def check_status_transition(role, current_status, new_status):
    role_rules = STATUS_TRANSITION_MATRIX.get(role, {})
    allowed_next = role_rules.get(current_status, [])
    return new_status in allowed_next

def sanitize_user_profile(user_doc):
    if not user_doc:
        return None
    safe_doc = dict(user_doc)
    safe_doc.pop("password_hash", None)
    safe_doc.pop("failed_login_attempts", None)
    safe_doc.pop("failed_logins", None)
    safe_doc.pop("lockout_until", None)
    safe_doc.pop("locked_until", None)
    return safe_doc
