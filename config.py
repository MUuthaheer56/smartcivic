"""
SmartCivic+ — Global Application Configuration
Loads configuration secrets exclusively from environment variables or .env file.
"""
import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()

def _require_secret(name: str) -> str:
    val = os.getenv(name)
    if not val or not val.strip():
        raise RuntimeError(
            f"CRITICAL: Required environment variable '{name}' is missing or empty. "
            f"Set a strong secret value before starting the application."
        )
    return val.strip()

class Config:
    SECRET_KEY            = _require_secret("SECRET_KEY")
    JWT_SECRET            = _require_secret("JWT_SECRET")
    MONGO_URI             = os.getenv("MONGO_URI", "mongodb://localhost:27017/smartcivic")
    GEMINI_API_KEY        = os.getenv("GEMINI_API_KEY", "")
    
    JWT_ACCESS_EXPIRES    = timedelta(minutes=30)
    JWT_REFRESH_EXPIRES   = timedelta(days=7)
    
    MAX_UPLOAD_SIZE       = 5 * 1024 * 1024  # 5MB
    UPLOAD_FOLDER         = "static/uploads/issues"
    ALLOWED_EXTENSIONS    = {"jpg", "jpeg", "png", "webp"}
    
    SLA_CHECK_INTERVAL    = 900  # 15 minutes
    DEBUG                 = False
    
    # Cookie secure flag – set COOKIE_SECURE=false for local HTTP development
    COOKIE_SECURE         = os.getenv("COOKIE_SECURE", "false").lower() == "true"
    
    # OSRM router endpoint
    OSRM_BASE             = os.getenv("OSRM_BASE", "http://router.project-osrm.org")
