"""
SmartCivic+ — Structured JSON Logging Service
Outputs rotated JSON-formatted logs to logs/smartcivic.log.
"""
import os
import json
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime

# Setup logs directory
log_dir = os.path.join(os.getcwd(), 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'smartcivic.log')

# Setup JSON formatter and rotating handler
logger = logging.getLogger("smartcivic_json")
logger.setLevel(logging.INFO)

# Avoid adding duplicate handlers if already loaded
if not logger.handlers:
    handler = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=5)
    logger.addHandler(handler)

# Optional Sentry SDK Error Tracking Integration
sentry_dsn = os.getenv("SENTRY_DSN")
if sentry_dsn:
    try:
        import sentry_sdk
        sentry_sdk.init(
            dsn=sentry_dsn,
            traces_sample_rate=1.0,
            profiles_sample_rate=1.0,
        )
        print("[Logger Service] Sentry error tracking initialized successfully.")
    except Exception as _sentry_err:
        print(f"[Logger Service] Could not initialize Sentry: {_sentry_err}")

class MongoJSONEncoder(json.JSONEncoder):
    def default(self, o):
        from bson import ObjectId
        from datetime import datetime
        if isinstance(o, ObjectId):
            return str(o)
        if isinstance(o, datetime):
            return o.isoformat()
        return super().default(o)

SENSITIVE_LOG_KEYS = {
    "password", "password_hash", "new_password", "token", "access_token",
    "refresh_token", "secret", "api_key", "jwt_secret", "phone", "phone_number"
}

def _redact_sensitive_data(val):
    if isinstance(val, dict):
        redacted = {}
        for k, v in val.items():
            if k.lower() in SENSITIVE_LOG_KEYS:
                redacted[k] = "[REDACTED]"
            else:
                redacted[k] = _redact_sensitive_data(v)
        return redacted
    elif isinstance(val, list):
        return [_redact_sensitive_data(item) for item in val]
    return val

def _write_log(log_type: str, data: dict):
    """
    Formulates a JSON log string and writes it to the log file with PII and credential redaction (Plan 3.5).
    """
    log_entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "log_type": log_type
    }
    safe_data = _redact_sensitive_data(data)
    log_entry.update(safe_data)
    try:
        logger.info(json.dumps(log_entry, cls=MongoJSONEncoder))
    except Exception as e:
        print(f"[Logging System] Error writing log: {e}")

def log_api_request(method: str, path: str, user_id: str, status_code: int, duration_ms: float):
    _write_log("api_request", {
        "method": method,
        "path": path,
        "user_id": str(user_id) if user_id else "anonymous",
        "status_code": status_code,
        "duration_ms": duration_ms
    })

def log_ai_call(task: str, provider: str, success: bool, confidence: float, duration_ms: float, error: str = None):
    _write_log("ai_call", {
        "task": task,
        "provider": provider,
        "success": success,
        "confidence": confidence,
        "duration_ms": duration_ms,
        "error": error
    })

def log_notification(event: str, recipient_id: str, delivery_status: str, error: str = None):
    _write_log("notification", {
        "event": event,
        "recipient_id": str(recipient_id),
        "delivery_status": delivery_status,
        "error": error
    })

def log_error(error_msg: str, context: dict = None):
    _write_log("error", {
        "message": error_msg,
        "context": context or {}
    })

def log_security_event(event_type: str, user_id: str, ip: str, details: dict = None):
    _write_log("security_event", {
        "event_type": event_type,
        "user_id": str(user_id) if user_id else "anonymous",
        "ip": ip,
        "details": details or {}
    })
