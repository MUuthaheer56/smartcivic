"""
SmartCivic+ — Global Application Configuration
Loads configuration secrets exclusively from environment variables or .env file.
"""
import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()

_PLACEHOLDER_TOKENS = ("replace_", "your_", "changeme", "changethis", "<", "example")

def _require_secret(name: str, min_length: int = 16) -> str:
    raw = os.getenv(name)
    val = (raw or "").strip()
    if not val:
        raise RuntimeError(
            f"CRITICAL: Required environment variable '{name}' is missing or empty. "
            f"Set a strong secret value before starting the application."
        )
    lowered = val.lower()
    for token in _PLACEHOLDER_TOKENS:
        if token in lowered:
            raise RuntimeError(
                f"CRITICAL: Environment variable '{name}' still contains a placeholder "
                f"value ('{token}' detected). Copy .env.example -> .env and replace the "
                f"placeholder with a real secret generated with `openssl rand -hex 32`."
            )
    if len(val) < min_length:
        raise RuntimeError(
            f"CRITICAL: Environment variable '{name}' is too short ({len(val)} chars). "
            f"Minimum length is {min_length} characters — use `openssl rand -hex 32`."
        )
    return val

def _mongo_client_kwargs() -> dict:
    """
    Hardened default MongoClient arguments for SmartCivic+.
    These are merged with any query-string parameters that already appear in
    MONGO_URI, so operators can still override individual values on a
    per-environment basis.  See scripts/harden_mongo.py → bootstrap URIs for
    the recommended parameter set.

    Safe defaults:
      * serverSelectionTimeoutMS = 5000   — fast fail if MongoDB is gone
      * connectTimeoutMS         = 5000
      * socketTimeoutMS          = 60000  — kill slow queries before 60s gunicorn timeout
      * maxPoolSize              = 100    — match maxIncomingConnections / worker count
      * minPoolSize              = 5
      * heartbeatFrequencyMS     = 5000   — detect primary failover faster in replicasets
      * retryWrites              = True   — transparently retry once-safe writes
      * retryReads               = True
      * w                        = "majority"  — no silent rollbacks on primary failover
      * journal                  = True        — ensure writes are durable to disk
      * directConnection         = False       — obey replica set topology
      * waitQueueTimeoutMS       = 10000       — don't park web workers forever waiting for a socket
    """
    return dict(
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
        socketTimeoutMS=60_000,
        maxPoolSize=int(os.getenv("MONGO_MAX_POOL", "100")),
        minPoolSize=int(os.getenv("MONGO_MIN_POOL", "5")),
        heartbeatFrequencyMS=5000,
        retryWrites=True,
        retryReads=True,
        w="majority",
        journal=True,
        directConnection=False,
        waitQueueTimeoutMS=10_000,
    )


class Config:
    SECRET_KEY            = _require_secret("SECRET_KEY")
    JWT_SECRET            = _require_secret("JWT_SECRET")
    JWT_SECRET_KEY        = JWT_SECRET
    MONGO_URI             = os.getenv("MONGO_URI", "mongodb://localhost:27017/smartcivic")
    MONGO_CLIENT_KWARGS   = _mongo_client_kwargs()
    GEMINI_API_KEY        = os.getenv("GEMINI_API_KEY", "")
    ADMIN_INVITE_CODE     = os.getenv("ADMIN_INVITE_CODE", "").strip()
    
    JWT_ACCESS_EXPIRES    = timedelta(minutes=30)
    JWT_REFRESH_EXPIRES   = timedelta(days=7)
    
    JWT_ACCESS_EXPIRES_MINUTES = 30
    JWT_REFRESH_EXPIRES_DAYS   = 7
    
    MAX_UPLOAD_SIZE       = 10 * 1024 * 1024  # 10MB
    MAX_IMAGE_BYTES       = 10 * 1024 * 1024  # 10MB
    PRIVATE_UPLOAD_DIR    = os.getenv("PRIVATE_UPLOAD_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads"))
    UPLOAD_FOLDER         = os.getenv("UPLOAD_FOLDER", os.path.join(PRIVATE_UPLOAD_DIR, "issues"))
    VERIFICATION_FOLDER   = os.getenv("VERIFICATION_FOLDER", os.path.join(PRIVATE_UPLOAD_DIR, "verification_docs"))
    RESOLUTION_FOLDER     = os.getenv("RESOLUTION_FOLDER", os.path.join(PRIVATE_UPLOAD_DIR, "resolution"))
    ALLOWED_EXTENSIONS    = {"jpg", "jpeg", "png", "webp"}
    ALLOWED_MIME_TYPES    = ["image/jpeg", "image/png", "image/webp"]
    
    # Canonical SLA Table (P0: 1h, P1: 4h, P2: 24h, P3: 72h)
    SLA_HOURS             = {"P0": 1, "P1": 4, "P2": 24, "P3": 72, "critical": 1, "high": 4, "medium": 24, "low": 72}
    SLA_CHECK_INTERVAL    = 900  # 15 minutes
    
    # Duplicate detection
    DUPLICATE_RADIUS_METERS = 200
    DUPLICATE_THRESHOLD     = 0.85
    
    # Worker matching
    MAX_WORKER_RECOMMENDATIONS = 5
    
    # ML & Computer Vision
    VISION_ENABLED           = os.getenv("VISION_ENABLED", "false").lower() == "true"
    YOLO_MODEL_PATH          = os.getenv("YOLO_MODEL_PATH", "ml/models/road_damage_v1.onnx")
    YOLO_CONFIDENCE_THRESHOLD = 0.40

    # Master Implementation Plan Feature Flags & AI Operation Modes
    AI_MODE                     = os.getenv("AI_MODE", "local").lower()
    AI_LOCAL_TEXT_ENABLED       = os.getenv("AI_LOCAL_TEXT_ENABLED", "false").lower() == "true"
    AI_LOCAL_DETECTOR_ENABLED   = os.getenv("AI_LOCAL_DETECTOR_ENABLED", "false").lower() == "true"
    AI_EMBED_DUPLICATES_ENABLED = os.getenv("AI_EMBED_DUPLICATES_ENABLED", "false").lower() == "true"
    AI_IMAGE_GATE_ENABLED       = os.getenv("AI_IMAGE_GATE_ENABLED", "false").lower() == "true"
    AI_REPAIR_V2_ENABLED        = os.getenv("AI_REPAIR_V2_ENABLED", "false").lower() == "true"
    AI_ML_PRIORITY_SHADOW       = os.getenv("AI_ML_PRIORITY_SHADOW", "false").lower() == "true"

    # Phase 3: Image Trust Gate Constants
    IMAGE_GATE_MIN_WIDTH              = int(os.getenv("IMAGE_GATE_MIN_WIDTH", "320"))
    IMAGE_GATE_MIN_HEIGHT             = int(os.getenv("IMAGE_GATE_MIN_HEIGHT", "240"))
    IMAGE_GATE_BLUR_THRESHOLD         = float(os.getenv("IMAGE_GATE_BLUR_THRESHOLD", "80.0"))
    IMAGE_GATE_DARK_THRESHOLD         = float(os.getenv("IMAGE_GATE_DARK_THRESHOLD", "35.0"))
    IMAGE_GATE_OVEREXPOSED_THRESHOLD  = float(os.getenv("IMAGE_GATE_OVEREXPOSED_THRESHOLD", "235.0"))
    IMAGE_GATE_HASH_HAMMING_THRESHOLD = int(os.getenv("IMAGE_GATE_HASH_HAMMING_THRESHOLD", "5"))
    
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
        "noise":       "sanitation",
        "other":       "roads"
    }
    CATEGORY_TO_DEPT = CATEGORY_TO_DEPARTMENT

    # Skill mapping
    ISSUE_TYPE_TO_SKILLS = {
        "pothole":         ["road_repair", "pothole_repair"],
        "road_collapse":   ["road_repair", "heavy_machinery"],
        "water_leak":      ["plumbing", "pipe_repair"],
        "power_outage":    ["electrical", "transformer_repair"],
        "garbage":         ["sanitation", "waste_removal"],
        "noise_violation": ["noise_monitoring", "general_maintenance"],
        "other":           ["general_maintenance"]
    }
    
    DEBUG                 = False
    _flask_env            = os.getenv("FLASK_ENV", os.getenv("ENV", "production")).lower()
    COOKIE_SECURE         = os.getenv("COOKIE_SECURE", "false" if _flask_env == "development" else "true").lower() == "true"
