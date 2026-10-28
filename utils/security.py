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


from constants.states import (
    STATUS_TRANSITION_MATRIX,
    ROLE_TRANSITIONS,
    validate_state_transition
)

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
    return validate_state_transition(current_status, new_status, role=role)

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

def can_view_file(db, user_id, role, kind, filename: str) -> bool:
    """
    Authorization rules for private uploads:
    - KINDS = {'docs', 'verification_docs', 'issues', 'resolution'}
    - ID/verification docs only for the owner, officers and admins.
    - Issue photos for the reporter, assigned worker, officers of the department, and admins.
    - Resolution photos for the same plus the reporter.
    - Look up the owning record in MongoDB by stored filename; deny if no record is found.
    """
    if not user_id or not role or not kind or not filename:
        return False

    role = str(role).lower()
    user_id_str = str(user_id)
    safe_fn = os.path.basename(filename)

    if role == "admin":
        return True

    if kind in ["docs", "verification_docs"]:
        user = db.users.find_one({"$or": [
            {"verification_doc": {"$regex": safe_fn}},
            {"documents": {"$regex": safe_fn}}
        ]})
        if not user:
            return False
            
        if role == "officer":
            return True
        return str(user.get("_id")) == user_id_str

    elif kind in ["issues", "resolution"]:
        issue = db.issues.find_one({"$or": [
            {"images.filename": safe_fn},
            {"images.url": {"$regex": safe_fn}},
            {"images.filepath": {"$regex": safe_fn}},
            {"media_urls": {"$regex": safe_fn}},
            {"photos": {"$regex": safe_fn}},
            {"resolution_notes.photos": {"$regex": safe_fn}},
            {"resolution_notes.after_image": {"$regex": safe_fn}},
            {"ctve_photo_url": {"$regex": safe_fn}}
        ]})
        if not issue:
            return False

        reporter_id = str(issue.get("citizen_id") or issue.get("reporter_id") or issue.get("user_id") or "")
        assigned_worker = str(issue.get("worker_id") or issue.get("assigned_worker_id") or issue.get("assigned_to") or "")
        issue_dept = (issue.get("department") or issue.get("category") or "").lower()

        # Reporter can view issue and resolution photos
        if reporter_id and reporter_id == user_id_str:
            return True

        # Assigned worker can view issue and resolution photos
        if assigned_worker and assigned_worker == user_id_str:
            return True

        # Officers of the department can view
        if role == "officer":
            officer = db.users.find_one({"_id": ObjectId(user_id)}) if ObjectId.is_valid(user_id_str) else None
            officer_dept = (officer.get("department") or "").lower() if officer else ""
            if not officer_dept or officer_dept == "all" or officer_dept == issue_dept:
                return True

        return False

    return False

