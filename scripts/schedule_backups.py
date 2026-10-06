"""
SmartCivic v2 — Automated Backup Scheduler Utility
Schedules automated periodic snapshots of MongoDB collections to zip archives.
"""

import time
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from scripts.backup_db import run_backup

def start_scheduled_backups(interval_hours=24):
    print(f"[Backup Scheduler] Starting automated database backup runner (Interval: {interval_hours} hours)...")
    interval_seconds = interval_hours * 3600
    while True:
        try:
            print(f"\n[Backup Scheduler] Triggering scheduled database backup sweep...")
            run_backup()
        except Exception as ex:
            print(f"[Backup Scheduler] Backup sweep error: {ex}")
        time.sleep(interval_seconds)

if __name__ == "__main__":
    start_scheduled_backups(interval_hours=24)
