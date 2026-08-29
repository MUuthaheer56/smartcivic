import jwt
import bcrypt
from datetime import datetime, timedelta
from functools import wraps
from flask import g, request, jsonify, current_app
from bson import ObjectId

def hash_password(plain_text: str) -> str:
    return bcrypt.hashpw(plain_text.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def check_password(plain_text: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain_text.encode('utf-8'), hashed.encode('utf-8'))
    except Exception:
        return False

def create_token(user_id: str, role: str, community_id: str) -> str:
    from app import db # import dynamically to avoid circular dependencies
    payload = {
        'user_id': str(user_id),
        'role': role,
        'community_id': str(community_id) if community_id else None,
        'exp': datetime.utcnow() + timedelta(hours=24),
        'iat': datetime.utcnow()
    }
    return jwt.encode(payload, current_app.config['JWT_SECRET'], algorithm='HS256')

def decode_token(token: str) -> dict:
    return jwt.decode(token, current_app.config['JWT_SECRET'], algorithms=['HS256'])

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        from app import db
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({'success': False, 'message': 'Missing token', 'data': None}), 401
        
        token = auth_header.split(' ')[1]
        try:
            payload = decode_token(token)
        except jwt.ExpiredSignatureError:
            return jsonify({'success': False, 'message': 'Token expired', 'data': None}), 401
        except jwt.InvalidTokenError:
            return jsonify({'success': False, 'message': 'Invalid token', 'data': None}), 401
            
        user = db.users.find_one({'_id': ObjectId(payload['user_id'])})
        if not user:
            return jsonify({'success': False, 'message': 'User not found', 'data': None}), 401
            
        g.user = {
            'user_id': str(user['_id']),
            'name': user['name'],
            'email': user['email'],
            'role': user['role'],
            'community_id': str(user['community_id']) if user.get('community_id') else None,
            'is_verified': user.get('is_verified', False),
            'is_anonymous_by_default': user.get('is_anonymous_by_default', False)
        }
        return f(*args, **kwargs)
    return decorated

def require_role(*roles):
    def decorator(f):
        @wraps(f)
        @require_auth
        def decorated(*args, **kwargs):
            if g.user['role'] not in roles:
                return jsonify({'success': False, 'message': 'Forbidden: Insufficient permissions', 'data': None}), 403
            return f(*args, **kwargs)
        return decorated
    return decorator

def require_verified(f):
    @wraps(f)
    @require_auth
    def decorated(*args, **kwargs):
        if not g.user['is_verified']:
            return jsonify({'success': False, 'message': 'Account not yet verified', 'data': None}), 403
        return f(*args, **kwargs)
    return decorated

def rate_limit(max_per_minute: int = 30):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            ip = request.remote_addr
            now = datetime.utcnow().timestamp()
            
            # Fetch the global rate limit store from app
            store = current_app.rate_limit_store
            
            if ip not in store:
                store[ip] = []
                
            # Keep only timestamps in last 60 seconds
            store[ip] = [ts for ts in store[ip] if now - ts < 60]
            
            if len(store[ip]) >= max_per_minute:
                return jsonify({'success': False, 'message': 'Too Many Requests: Rate limit exceeded', 'data': None}), 429
                
            store[ip].append(now)
            return f(*args, **kwargs)
        return decorated
    return decorator

import random
import hashlib
import json

# 1. Login IP Rate Limiter
MAX_ATTEMPTS = 5
LOCKOUT_MINUTES = 15

def rate_limit_login_by_ip(ip: str, db) -> tuple[bool, int]:
    """
    Returns (allowed, remaining_attempts).
    allowed=False means the IP is locked out.
    """
    now = datetime.utcnow()
    window_start = now - timedelta(minutes=LOCKOUT_MINUTES)
    rec = db.login_attempts.find_one({"ip": ip})
    if not rec:
        return True, MAX_ATTEMPTS
        
    # Reset window if it has expired
    if rec.get("window_start", now) < window_start:
        db.login_attempts.update_one(
            {"ip": ip},
            {"$set": {"attempts": 0, "window_start": now}}
        )
        return True, MAX_ATTEMPTS
        
    attempts = rec.get("attempts", 0)
    if attempts >= MAX_ATTEMPTS:
        return False, 0
    return True, MAX_ATTEMPTS - attempts

def record_failed_attempt(ip: str, db):
    db.login_attempts.update_one(
        {"ip": ip},
        {"$inc": {"attempts": 1},
         "$setOnInsert": {"window_start": datetime.utcnow()}},
        upsert=True
    )

def clear_login_attempts(ip: str, db):
    db.login_attempts.delete_one({"ip": ip})

# 2. OTP Verification
def send_otp_verification(user_id: str, channel: str, db) -> tuple[bool, str]:
    """
    channel: "email" | "sms"
    Returns (success, message).
    """
    otp = str(random.randint(100000, 999999))
    otp_hash = hashlib.sha256(otp.encode()).hexdigest()
    expires_at = datetime.utcnow() + timedelta(minutes=10)
    
    db.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {
            "otp_hash": otp_hash,
            "otp_expires_at": expires_at,
            "is_verified": False
        }}
    )
    
    user = db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        return False, "User not found"
        
    if channel == "email":
        _send_email_otp(user["email"], otp)
    elif channel == "sms":
        phone = user.get("phone")
        if not phone:
            return False, "User phone number not configured for SMS OTP"
        _send_sms_otp(phone, otp)
    else:
        return False, "Invalid channel"
        
    return True, f"OTP dispatched via {channel}"

def verify_otp(user_id: str, otp_input: str, db) -> tuple[bool, str]:
    otp_hash = hashlib.sha256(otp_input.encode()).hexdigest()
    user = db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        return False, "User not found"
    if datetime.utcnow() > user.get("otp_expires_at", datetime.min):
        return False, "OTP expired"
    if user.get("otp_hash") != otp_hash:
        return False, "Invalid OTP"
        
    db.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"is_verified": True}, "$unset": {"otp_hash": "", "otp_expires_at": ""}}
    )
    return True, "Verified"

def _send_email_otp(email: str, otp: str):
    try:
        import smtplib, os
        from email.mime.text import MIMEText
        msg = MIMEText(f"Your SmartCivic OTP is: {otp}\nExpires in 10 minutes.")
        msg["Subject"] = "SmartCivic Verification Code"
        msg["From"] = os.environ.get("SMTP_FROM", "noreply@smartcivic.gov")
        msg["To"] = email
        
        host = os.environ.get("SMTP_HOST", "localhost")
        user = os.environ.get("SMTP_USER", "")
        pwd = os.environ.get("SMTP_PASS", "")
        
        if not user or not pwd:
            print(f"[Email Fallback] Email: {email}, OTP: {otp}")
            return

        with smtplib.SMTP(host, 587) as s:
            s.starttls()
            s.login(user, pwd)
            s.send_message(msg)
    except Exception as e:
        print(f"[Email Error] {e}. OTP was: {otp}")

def _send_sms_otp(phone: str, otp: str):
    try:
        from twilio.rest import Client
        import os
        sid = os.environ.get("TWILIO_SID")
        token = os.environ.get("TWILIO_TOKEN")
        from_num = os.environ.get("TWILIO_FROM")
        if not sid or not token or not from_num:
            print(f"[SMS Fallback] Phone: {phone}, OTP: {otp}")
            return
        c = Client(sid, token)
        c.messages.create(
            body=f"SmartCivic OTP: {otp} (expires 10 min)",
            from_=from_num, to=f"+91{phone}"
        )
    except Exception as e:
        print(f"[SMS Error] {e}. OTP was: {otp}")

# 3. Audit Logging
def audit_log_action(user_id: str, action: str, meta: dict, db):
    """
    action examples: "LOGIN", "COMPLAINT_CREATE", "ASSIGN", "STATUS_CHANGE", "ADMIN_OVERRIDE"
    meta: arbitrary dict with context (complaint_id, old_status, new_status, etc.)
    """
    payload_str = json.dumps(meta, default=str, sort_keys=True)
    payload_hash = hashlib.sha256(payload_str.encode()).hexdigest()
    
    # Try getting remote address and headers inside request context
    ip = "system"
    user_agent = ""
    try:
        from flask import request
        if request:
            ip = request.remote_addr or "system"
            user_agent = request.headers.get("User-Agent", "")
    except Exception:
        pass

    entry = {
        "user_id": ObjectId(user_id) if isinstance(user_id, str) and ObjectId.is_valid(user_id) else user_id,
        "action": action,
        "meta": meta,
        "payload_hash": payload_hash,
        "ip": ip,
        "user_agent": user_agent,
        "timestamp": datetime.utcnow()
    }
    result = db.audit_logs.insert_one(entry)
    return result.inserted_id
