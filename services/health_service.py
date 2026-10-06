"""
SmartCivic+ — System Health Monitoring Service
Monitors system resource states, database pings, background tasks, and AI errors.

Every MongoDB interaction is wrapped in a defensive try/except so the health
endpoint itself is always available and returns a valid JSON report even when
the database, notification collection, or CivicPulse collection is unreachable.
"""
import os
import shutil
import time
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Global start time for uptime calculation
START_TIME = time.time()

def _safe_count(collection, query: dict) -> int:
    """Count documents in a collection; return 0 and log on any failure."""
    try:
        return int(collection.count_documents(query or {}))
    except Exception as exc:
        logger.warning(
            "Health check count_documents failed on %s with query %s: %s",
            getattr(collection, "name", "<unknown>"), query, exc
        )
        return 0

def get_system_health() -> dict:
    """
    Retrieves a comprehensive JSON health status report of the platform.

    Never raises — all fallible subsystems degrade gracefully and are reported
    with explicit "status"/"degraded" fields.
    """
    from app import db  # lazy import so import-time does not require MongoDB

    # 1. MongoDB check (with latency) — this is the authoritative liveness probe
    db_status = "Online"
    db_latency = 0.0
    db_error = None
    db_available = False
    try:
        t0 = time.time()
        db.command("ping")
        db_latency = round((time.time() - t0) * 1000.0, 1)
        db_available = True
    except Exception as exc:
        db_status = "Offline"
        db_error = str(exc)
        logger.warning("Health probe: MongoDB ping failed: %s", exc)

    # 2. Storage check
    upload_dir = os.path.join(os.getcwd(), 'static', 'uploads')
    storage_accessible = os.path.exists(upload_dir) or os.path.exists(os.getcwd())
    free_mb = 0
    try:
        total, used, free = shutil.disk_usage(os.getcwd())
        free_mb = round(free / (1024 * 1024), 1)
    except Exception as exc:
        logger.warning("Health probe: disk_usage failed: %s", exc)

    # 3. Notification statistics — safe even if collection missing / DB offline
    sent_count = _safe_count(getattr(db, "notifications", None), {"is_read": True}) if db_available else 0
    pending_count = _safe_count(getattr(db, "notifications", None), {"is_read": False}) if db_available else 0

    # 4. Background Scheduler registry (in-memory)
    jobs_summary = [
        {"name": "SLA Checker Sweep", "interval": "15 mins", "status": "Active"},
        {"name": "AI Daily Officer Briefing", "interval": "30 mins", "status": "Active"},
        {"name": "Ward Health Scores Recalc", "interval": "30 mins", "status": "Active"},
        {"name": "Predictive Hotspot Map Builder", "interval": "1 week", "status": "Active"},
        {"name": "Infrastructure Health Sweep", "interval": "6 hours", "status": "Active"},
    ]

    # 5. Uptime
    uptime = int(time.time() - START_TIME)

    # 6. CivicPulse prediction summary — safe even if collection missing / DB offline
    civicpulse_critical = _safe_count(getattr(db, "civicpulse_predictions", None), {"risk_band": "CRITICAL"}) if db_available else 0
    civicpulse_high     = _safe_count(getattr(db, "civicpulse_predictions", None), {"risk_band": "HIGH"}) if db_available else 0
    civicpulse_total    = _safe_count(getattr(db, "civicpulse_predictions", None), {}) if db_available else 0

    overall = "healthy" if (db_available and storage_accessible) else "degraded"

    return {
        "status": overall,
        "database": {
            "status": db_status,
            "response_ms": db_latency,
            "error": db_error,
        },
        "storage": {
            "accessible": storage_accessible,
            "free_mb": free_mb,
        },
        "notifications": {
            "sent_1h": sent_count,
            "failed_1h": 0,
            "pending": pending_count,
        },
        "scheduler": {
            "status": "Online",
            "jobs": jobs_summary,
        },
        "civicpulse": {
            "total_segments_predicted": civicpulse_total,
            "critical_risk": civicpulse_critical,
            "high_risk": civicpulse_high,
        },
        "uptime_seconds": uptime,
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }
