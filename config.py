"""
SmartCivic+ — Global Application Configuration
Loads configuration secrets exclusively from environment variables or .env file.
"""
import os
from datetime import timedelta
from dotenv import load_dotenv

# Load local .env file
load_dotenv()

def _require_secret(name, default=None):
    val = os.getenv(name)
    if val:
        return val
    if os.getenv("FLASK_ENV", "development").lower() == "production":
        raise RuntimeError(f"CRITICAL CONFIG ERROR: Missing required production secret environment variable: {name}")
    if default:
        return default
    import secrets
    return secrets.token_hex(32)

class Config:
    SECRET_KEY            = _require_secret("SECRET_KEY", "dev_fallback_secret_key_456")
    MONGO_URI             = os.getenv("MONGO_URI", "mongodb://localhost:27017/smartcivic")
    GEMINI_API_KEY        = os.getenv("GEMINI_API_KEY", "")
    
    JWT_SECRET            = _require_secret("JWT_SECRET", "dev_fallback_jwt_secret_789")
    JWT_ACCESS_EXPIRES    = timedelta(minutes=30)
    JWT_REFRESH_EXPIRES   = timedelta(days=7)
    
    MAX_UPLOAD_SIZE       = 5 * 1024 * 1024  # 5MB
    UPLOAD_FOLDER         = "static/uploads/issues"
    ALLOWED_EXTENSIONS    = {"jpg", "jpeg", "png", "webp"}
    
    SLA_CHECK_INTERVAL    = 900  # 15 minutes
    DEBUG                 = False  # Never True in production
    
    # OSRM router endpoint
    OSRM_BASE             = os.getenv("OSRM_BASE", "http://router.project-osrm.org")
