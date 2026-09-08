"""
SmartCivic — Authentication & Authorization Service
Implements user registration, password verification, token issuance, and role checking.
"""
from app import db
from routes.auth import hash_password, check_password, generate_tokens, decode_token
from bson import ObjectId
from datetime import datetime

VALID_ROLES = {"resident", "officer", "worker"}

def register_user(email: str, password: str, role: str, name: str) -> dict:
    if not email or not password or not role or not name:
        raise ValueError("Missing required fields: email, password, role, name")
    role = str(role).strip().lower()
    if role not in VALID_ROLES:
        raise ValueError(f"Invalid role '{role}'. Allowed: {VALID_ROLES}")
        
    email_clean = str(email).strip().lower()
    existing = db.users.find_one({"email": email_clean})
    if existing:
        raise ValueError("User with this email already exists.")
        
    pwd_hash = hash_password(password)
    user_doc = {
        "_id": ObjectId(),
        "name": name.strip(),
        "email": email_clean,
        "password_hash": pwd_hash,
        "role": role,
        "ward": "Ward 1",
        "created_at": datetime.utcnow()
    }
    db.users.insert_one(user_doc)
    
    # Return user dict without password hash
    return {
        "user_id": str(user_doc["_id"]),
        "name": user_doc["name"],
        "email": user_doc["email"],
        "role": user_doc["role"],
        "ward": user_doc["ward"]
    }

def login_user(email: str, password: str) -> dict:
    email_clean = str(email).strip().lower()
    user = db.users.find_one({"email": email_clean})
    if not user or not check_password(password, user.get("password_hash", "")):
        raise ValueError("Invalid email or password.")
        
    access_token, refresh_token = generate_tokens(str(user["_id"]), user["role"], user.get("ward", "Ward 1"))
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "role": user["role"],
        "user_id": str(user["_id"]),
        "name": user.get("name", "")
    }

def verify_token(token: str) -> dict:
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        raise PermissionError("Invalid or expired token.")
    return payload

def get_current_user(token: str) -> dict:
    payload = verify_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise PermissionError("Invalid token payload.")
    try:
        user = db.users.find_one({"_id": ObjectId(user_id)})
    except Exception:
        user = None
    if not user:
        raise PermissionError("User not found.")
    user["user_id"] = str(user["_id"])
    return user

def check_role(user: dict, required_role: str) -> bool:
    role = user.get("role") if isinstance(user, dict) else getattr(user, "role", None)
    if role != required_role:
        raise PermissionError(f"Access forbidden. Required role: '{required_role}', user role: '{role}'")
    return True
