from apscheduler.schedulers.background import BackgroundScheduler
from .drain_predictor import run_drain_prediction

def start_drain_scheduler(db):
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        func=lambda: run_drain_prediction(db),
        trigger="interval",
        hours=6,
        id="drain_prediction"
    )
    scheduler.start()
    return scheduler
