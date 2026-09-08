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
    ADMIN_INVITE_CODE     = os.getenv("ADMIN_INVITE_CODE", "").strip()
    
    JWT_ACCESS_EXPIRES    = timedelta(minutes=30)
    JWT_REFRESH_EXPIRES   = timedelta(days=7)
    
    JWT_ACCESS_EXPIRES_MINUTES = 30
    JWT_REFRESH_EXPIRES_DAYS   = 7
    
    MAX_UPLOAD_SIZE       = 10 * 1024 * 1024  # 10MB
    MAX_IMAGE_BYTES       = 10 * 1024 * 1024  # 10MB
    UPLOAD_FOLDER         = "static/uploads/issues"
    ALLOWED_EXTENSIONS    = {"jpg", "jpeg", "png", "webp"}
    ALLOWED_MIME_TYPES    = ["image/jpeg", "image/png", "image/webp"]
    
    # SLA
    SLA_HOURS             = {"critical": 4, "high": 24, "medium": 72, "low": 168}
    SLA_CHECK_INTERVAL    = 900  # 15 minutes
    
    # Duplicate detection
    DUPLICATE_RADIUS_METERS = 200
    DUPLICATE_THRESHOLD     = 0.85
    
    # Worker matching
    MAX_WORKER_RECOMMENDATIONS = 5
    
    # ML
    YOLO_MODEL_PATH          = "ml/models/pothole_yolov8n.onnx"
    YOLO_CONFIDENCE_THRESHOLD = 0.40
    
    # Routing
    ROUTING_ENGINE_URL       = os.getenv("ROUTING_ENGINE_URL", "http://router.project-osrm.org/route/v1/driving/")
    ROUTING_TIMEOUT_SECONDS  = 5
    OSRM_BASE                = os.getenv("OSRM_BASE", "http://router.project-osrm.org")
    
    # Department mapping
    CATEGORY_TO_DEPARTMENT = {
        "road":        "roads",
        "water":       "water_supply",
        "electricity": "electrical",
        "sanitation":  "sanitation",
        "drainage":    "drainage",
        "other":       "roads"
    }

    # Skill mapping
    ISSUE_TYPE_TO_SKILLS = {
        "pothole":       ["road_repair", "pothole_repair"],
        "road_collapse": ["road_repair", "heavy_machinery"],
        "water_leak":    ["plumbing", "pipe_repair"],
        "power_outage":  ["electrical", "transformer_repair"],
        "garbage":       ["sanitation", "waste_removal"],
        "other":         ["general_maintenance"]
    }
    
    DEBUG                 = False
    COOKIE_SECURE         = os.getenv("COOKIE_SECURE", "false").lower() == "true"
