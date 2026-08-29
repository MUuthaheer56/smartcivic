"""
SmartCivic — Background Scheduler Service
Replaces manual stale/SLA checks on every dashboard request.
Jobs run on their own schedule, not on HTTP requests.
"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
import atexit

_scheduler = None


def _run_stale_checks():
    """Runs every 6 hours — checks stale issues and SLA breaches."""
    try:
        from services.score_service import check_stale_issues
        from services.sla_service import check_and_flag_sla_breaches
        check_stale_issues()
        check_and_flag_sla_breaches()
        print("[Scheduler] Stale + SLA checks complete.")
    except Exception as e:
        print(f"[Scheduler] Stale check error: {e}")


def _run_drain_prediction():
    """Runs every 6 hours — computes drain risk for all communities."""
    try:
        from app import db
        from flask import current_app
        communities = list(db.communities.find({}, {"_id": 1}))
        from ai.drain_predictor import compute_drain_risks
        api_key = current_app.config.get('OPENWEATHER_API_KEY', '')
        for comm in communities:
            compute_drain_risks(str(comm['_id']), api_key)
        print("[Scheduler] Drain prediction complete.")
    except Exception as e:
        print(f"[Scheduler] Drain prediction error: {e}")


def _run_weekly_digest():
    """Runs every Monday at 08:00 — sends weekly digest emails."""
    try:
        from app import db
        from services.notification_service import send_weekly_digest
        communities = list(db.communities.find({}, {"_id": 1}))
        for comm in communities:
            send_weekly_digest(str(comm['_id']))
        print("[Scheduler] Weekly digest sent.")
    except Exception as e:
        print(f"[Scheduler] Weekly digest error: {e}")


def start_scheduler(app):
    """Start the background scheduler. Call once from create_app()."""
    global _scheduler
    if _scheduler and _scheduler.running:
        return

    _scheduler = BackgroundScheduler()

    # Every 6 hours — stale issue + SLA breach sweep
    _scheduler.add_job(
        func=_run_stale_checks,
        trigger=IntervalTrigger(hours=6),
        id='stale_sla_check',
        name='Stale & SLA Check',
        replace_existing=True
    )

    # Every 6 hours — drain risk prediction
    _scheduler.add_job(
        func=_run_drain_prediction,
        trigger=IntervalTrigger(hours=6),
        id='drain_prediction',
        name='Drain Blockage Prediction',
        replace_existing=True
    )

    # Every Monday 08:00 — weekly digest
    _scheduler.add_job(
        func=_run_weekly_digest,
        trigger=CronTrigger(day_of_week='mon', hour=8, minute=0),
        id='weekly_digest',
        name='Weekly Email Digest',
        replace_existing=True
    )

    # Hourly — SLA breach check
    _scheduler.add_job(
        func=_run_sla_breach_job,
        trigger=IntervalTrigger(hours=1),
        id='sla_breach_job',
        name='Hourly SLA Breach Check',
        replace_existing=True
    )

    # Every 60 seconds — FCM notification flush
    _scheduler.add_job(
        func=_run_notification_flush_job,
        trigger=IntervalTrigger(seconds=60),
        id='notification_flush_job',
        name='FCM Notification Flush',
        replace_existing=True
    )

    # Monthly (day 1, 00:01) — monthly civic decay
    _scheduler.add_job(
        func=_run_decay_job,
        trigger=CronTrigger(day=1, hour=0, minute=1),
        id='decay_job',
        name='Monthly Civic Decay Job',
        replace_existing=True
    )

    _scheduler.start()
    atexit.register(lambda: _scheduler.shutdown())
    print("[Scheduler] Background scheduler started.")


from datetime import datetime, timedelta

SLA_HOURS = {
    'water': 24,
    'sewage': 24,
    'garbage': 48,
    'streetlight': 72,
    'noise': 120,
    'pothole': 168,
    'other': 168
}

def _run_sla_breach_job():
    """Runs hourly background SLA deadline breach sweeps."""
    try:
        from app import db
        from services.sla_service import escalate_sla_breach
        
        now = datetime.utcnow()
        active_statuses = ["pending_validation", "validated", "assigned", "in_progress"]
        active = list(db.issues.find(
            {"status": {"$in": active_statuses}},
            {"_id": 1, "category": 1, "created_at": 1, "sla_status": 1, "escalation_level": 1}
        ))
        breached_count = 0
        for comp in active:
            category = comp.get("category", "other")
            # Get category-specific SLA, fallback to 72 hours
            sla_hours = SLA_HOURS.get(category, 72)
            
            created_at = comp.get("created_at")
            if isinstance(created_at, str):
                created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00")).replace(tzinfo=None)
                
            deadline = created_at + timedelta(hours=sla_hours)
            if now > deadline and comp.get("sla_status") != "BREACHED":
                escalate_sla_breach(str(comp["_id"]), db)
                breached_count += 1
                
        if breached_count:
            db.job_logs.insert_one({
                "job": "sla_breach_job",
                "run_at": now,
                "breached_count": breached_count
            })
        print(f"[Scheduler] SLA breach sweep complete: {breached_count} escalated.")
    except Exception as e:
        print(f"[Scheduler] SLA breach sweep error: {e}")


def _run_notification_flush_job():
    """Runs every 60 seconds — flushes PENDING notifications."""
    try:
        from app import db
        MAX_RETRIES = 3
        
        pending = list(db.notifications.find({
            "delivery_status": {"$in": ["PENDING", "FAILED"]},
            "retry_count": {"$lt": MAX_RETRIES}
        }))
        if not pending:
            return
            
        delivered = 0
        for notif in pending:
            user_id = notif.get("user_id")
            user = db.users.find_one({"_id": user_id}, {"fcm_token": 1})
            token = user.get("fcm_token") if user else None
            
            success = False
            if token:
                try:
                    import requests, os
                    key = os.environ.get("FIREBASE_SERVER_KEY")
                    if key:
                        resp = requests.post(
                            "https://fcm.googleapis.com/fcm/send",
                            headers={"Authorization": f"key={key}", "Content-Type": "application/json"},
                            json={"to": token, "notification": {"title": "SmartCivic", "body": notif.get("message", "")}},
                            timeout=4
                        )
                        success = (resp.status_code == 200)
                except Exception:
                    pass
                    
            retry_count = notif.get("retry_count", 0) + 1
            if success:
                db.notifications.update_one(
                    {"_id": notif["_id"]},
                    {"$set": {"delivery_status": "DELIVERED", "delivered_at": datetime.utcnow()}}
                )
                delivered += 1
            elif retry_count >= MAX_RETRIES:
                db.notifications.update_one(
                    {"_id": notif["_id"]},
                    {"$set": {"delivery_status": "PERMANENTLY_FAILED"}, "$inc": {"retry_count": 1}}
                )
            else:
                db.notifications.update_one(
                    {"_id": notif["_id"]},
                    {"$set": {"delivery_status": "FAILED"}, "$inc": {"retry_count": 1}}
                )
        if delivered:
            print(f"[Scheduler] Notification flush complete: {delivered} sent.")
    except Exception as e:
        print(f"[Scheduler] Notification flush error: {e}")


def _run_decay_job():
    """Runs on the 1st of each month at 00:01 — decays civic score for inactive users."""
    try:
        from app import db
        from services.verification_service import decay_civic_points
        count = decay_civic_points(db)
        db.job_logs.insert_one({
            "job": "decay_job",
            "run_at": datetime.utcnow(),
            "decayed_user_count": count
        })
        print(f"[Scheduler] Civic score decay complete: {count} users processed.")
    except Exception as e:
        print(f"[Scheduler] Civic score decay error: {e}")
