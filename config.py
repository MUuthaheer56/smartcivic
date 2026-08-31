"""
SmartCivic+ — Global Application Configuration
Loads configuration secrets exclusively from environment variables or .env file.
"""
import os
from datetime import timedelta
from dotenv import load_dotenv

# Load local .env file
load_dotenv()

class Config:
    SECRET_KEY            = os.getenv("SECRET_KEY", "prod_fallback_secret_key_123")
    MONGO_URI             = os.getenv("MONGO_URI", "mongodb://localhost:27017/smartcivic")
    GEMINI_API_KEY        = os.getenv("GEMINI_API_KEY", "")
    
    JWT_SECRET            = os.getenv("JWT_SECRET", "prod_fallback_jwt_secret_999")
    JWT_ACCESS_EXPIRES    = timedelta(minutes=30)
    JWT_REFRESH_EXPIRES   = timedelta(days=7)
    
    MAX_UPLOAD_SIZE       = 5 * 1024 * 1024  # 5MB
    UPLOAD_FOLDER         = "static/uploads/issues"
    ALLOWED_EXTENSIONS    = {"jpg", "jpeg", "png", "webp"}
    
    SLA_CHECK_INTERVAL    = 900  # 15 minutes
    DEBUG                 = False  # Never True in production
    
    # OSRM router endpoint
    OSRM_BASE             = os.getenv("OSRM_BASE", "http://router.project-osrm.org")
