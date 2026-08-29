import os
import re
import time
import uuid
import hmac
import hashlib
import jwt
from functools import wraps
from typing import Dict, Any, Optional
from dataclasses import dataclass

JWT_SECRET = os.getenv("JWT_SECRET", "DEV_INSECURE_SECRET_MUST_BE_REPLACED_IN_ENV")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_SECONDS = 3600 * 8  # 8 hours

# Rate limiting storage (In-memory token bucket; production uses Redis)
RATE_LIMIT_STORE: Dict[str, list] = {}

class SecurityError(Exception):
    pass

class AuthenticationError(SecurityError):
    pass

class AuthorizationError(SecurityError):
    pass

def generate_uuid() -> str:
    return str(uuid.uuid4())

def hash_password(password: str) -> str:
    """Generate salted password hash using PBKDF2-HMAC-SHA256."""
    salt = os.urandom(16)
    pwd_hash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100_000)
    return f"{salt.hex()}${pwd_hash.hex()}"

def verify_password(stored_hash: str, password_attempt: str) -> bool:
    """Constant-time verification of password hash."""
    try:
        salt_hex, hash_hex = stored_hash.split('$')
        salt = bytes.fromhex(salt_hex)
        expected_hash = bytes.fromhex(hash_hex)
        attempt_hash = hashlib.pbkdf2_hmac('sha256', password_attempt.encode('utf-8'), salt, 100_000)
        return hmac.compare_digest(expected_hash, attempt_hash)
    except Exception:
        return False

def create_access_token(user_id: str, role: str, email: str) -> str:
    payload = {
        "sub": user_id,
        "role": role,
        "email": email,
        "iat": int(time.time()),
        "exp": int(time.time()) + JWT_EXPIRATION_SECONDS
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def decode_access_token(token: str) -> Dict[str, Any]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise AuthenticationError("Session has expired. Please log in again.")
    except jwt.InvalidTokenError:
        raise AuthenticationError("Invalid authentication token.")

def sanitize_input(text: Optional[str]) -> str:
    """Sanitize user input to prevent HTML/Script injection attacks."""
    if not text:
        return ""
    # Strip HTML tags and encode critical entities
    clean = re.sub(r'<[^>]*?>', '', text)
    clean = clean.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;').replace("'", '&#x27;')
    return clean.strip()

def check_rate_limit(client_ip: str, max_requests: int = 30, window_seconds: int = 60) -> bool:
    """Sliding-window rate limiter."""
    now = time.time()
    if client_ip not in RATE_LIMIT_STORE:
        RATE_LIMIT_STORE[client_ip] = []
    
    # Prune old timestamps
    RATE_LIMIT_STORE[client_ip] = [ts for ts in RATE_LIMIT_STORE[client_ip] if now - ts < window_seconds]
    
    if len(RATE_LIMIT_STORE[client_ip]) >= max_requests:
        return False
        
    RATE_LIMIT_STORE[client_ip].append(now)
    return True
