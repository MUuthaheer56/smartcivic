"""
SmartCivic+ — Distributed Scheduler Lock
Prevents background jobs (SLA escalations, sweeps) from firing N times
under multi-worker Gunicorn deployments using atomic MongoDB lease locking.
"""
import os
import logging
from datetime import datetime, timedelta
from contextlib import contextmanager
from pymongo.errors import DuplicateKeyError
from app import db

logger = logging.getLogger(__name__)

def acquire_scheduler_lock(lock_name: str, ttl_seconds: int = 180) -> bool:
    """
    Attempts to atomically acquire a named lock in MongoDB.
    Returns True if the lock was acquired, False if held by another worker.
    """
    now = datetime.utcnow()
    expires_at = now + timedelta(seconds=ttl_seconds)
    my_owner = f"{os.getpid()}_{id(now)}"

    try:
        # Atomic find and update: acquire if lock does not exist or has expired
        res = db.scheduler_locks.find_one_and_update(
            {
                "_id": lock_name,
                "$or": [
                    {"locked": False},
                    {"expires_at": {"$lt": now}}
                ]
            },
            {
                "$set": {
                    "locked": True,
                    "owner": my_owner,
                    "locked_at": now,
                    "expires_at": expires_at
                }
            },
            upsert=False
        )
        if res:
            return True

        # If document does not exist yet, attempt insert
        try:
            db.scheduler_locks.insert_one({
                "_id": lock_name,
                "locked": True,
                "owner": my_owner,
                "locked_at": now,
                "expires_at": expires_at
            })
            return True
        except DuplicateKeyError:
            # Another worker beat us to insertion
            return False
    except Exception as exc:
        logger.warning(f"[SchedulerLock] Failed to evaluate lock '{lock_name}': {exc}")
        return False

def release_scheduler_lock(lock_name: str) -> None:
    """Releases the lock so another cycle can acquire it immediately."""
    try:
        db.scheduler_locks.update_one(
            {"_id": lock_name},
            {"$set": {"locked": False, "expires_at": datetime.utcnow()}}
        )
    except Exception as exc:
        logger.warning(f"[SchedulerLock] Failed to release lock '{lock_name}': {exc}")

@contextmanager
def scheduler_lock(lock_name: str, ttl_seconds: int = 180):
    """
    Context manager for background scheduler jobs.
    Yields True if lock was acquired, False otherwise.
    Releases lock upon completion if acquired.
    """
    acquired = acquire_scheduler_lock(lock_name, ttl_seconds=ttl_seconds)
    try:
        yield acquired
    finally:
        if acquired:
            release_scheduler_lock(lock_name)
