"""
SmartCivic+ — Verification Document Retention Service
Deletes citizen verification documents N days after approval or rejection,
recording immutable audit_log entries and respecting scheduler leases.
"""
import os
import logging
from datetime import datetime, timedelta
from app import db
from config import Config
from services.scheduler_lock import scheduler_lock

logger = logging.getLogger(__name__)

def purge_expired_verification_documents(db_instance=None, retention_days: int = None) -> dict:
    """
    Scans for users approved or rejected more than `retention_days` ago who still
    have a verification document on disk. Deletes the physical file, unsets the
    document reference in the user record, and writes an audit_logs entry.
    """
    target_db = db_instance if db_instance is not None else db
    if retention_days is None:
        retention_days = int(os.getenv("VERIFICATION_DOC_RETENTION_DAYS", "30"))

    cutoff_date = datetime.utcnow() - timedelta(days=retention_days)

    query = {
        "verification_doc": {"$exists": True, "$ne": None, "$ne": ""},
        "$or": [
            {"verified_at": {"$lte": cutoff_date}},
            {"rejected_at": {"$lte": cutoff_date}},
            {"reviewed_at": {"$lte": cutoff_date}}
        ]
    }

    candidates = list(target_db.users.find(query))
    deleted_count = 0
    errors = []

    for user in candidates:
        user_id = str(user.get("_id"))
        doc_url = str(user.get("verification_doc", ""))
        filename = doc_url.split("/")[-1] if "/" in doc_url else doc_url
        
        # Try both private upload folder and fallback folder
        upload_dir = getattr(Config, "PRIVATE_UPLOAD_DIR", os.path.join(os.getcwd(), "uploads"))
        primary_path = os.path.join(upload_dir, "verification_docs", filename)
        alt_path = os.path.join(os.getcwd(), "uploads", "verification_docs", filename)
        
        file_removed = False
        for p in [primary_path, alt_path]:
            if os.path.exists(p):
                try:
                    os.remove(p)
                    file_removed = True
                except Exception as e:
                    errors.append(f"Failed to delete {p}: {e}")

        # Update user record to indicate document purged
        target_db.users.update_one(
            {"_id": user["_id"]},
            {
                "$set": {
                    "verification_doc": None,
                    "verification_doc_purged": True,
                    "verification_doc_purged_at": datetime.utcnow()
                }
            }
        )

        # Write immutable audit log
        target_db.audit_logs.insert_one({
            "action": "verification_doc_purged",
            "target_user_id": user_id,
            "filename": filename,
            "retention_days": retention_days,
            "decision": user.get("verification_status", "approved"),
            "timestamp": datetime.utcnow(),
            "file_deleted": file_removed
        })

        deleted_count += 1
        logger.info(f"[RetentionService] Purged verification doc {filename} for user {user_id}")

    return {
        "status": "success",
        "scanned": len(candidates),
        "purged": deleted_count,
        "errors": errors
    }

def run_retention_purge_job():
    """Background scheduler worker task protected by scheduler lock."""
    with scheduler_lock("verification_doc_retention_purge", ttl_seconds=300) as acquired:
        if not acquired:
            return {"status": "skipped", "reason": "lock_held"}
        return purge_expired_verification_documents()

