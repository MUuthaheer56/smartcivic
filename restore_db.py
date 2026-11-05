"""
SmartCivic — Database Restoration Utility Script
Restores database collections from a timestamped backup archive and rebuilds all indexes.
"""
import sys
import os

from scripts.backup_db import run_restore

def main():
    if len(sys.argv) < 2:
        backups_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backups")
        if os.path.exists(backups_dir):
            files = [f for f in os.listdir(backups_dir) if f.endswith(".zip")]
            files.sort(reverse=True)
            if files:
                print(f"[Restore] No backup file specified. Latest available: {files[0]}")
                backup_name = files[0]
            else:
                print("Usage: python restore_db.py <backup_filename.zip>")
                sys.exit(1)
        else:
            print("Usage: python restore_db.py <backup_filename.zip>")
            sys.exit(1)
    else:
        backup_name = sys.argv[1]

    ok = run_restore(backup_name)
    if ok:
        print("[Restore] Database restored and indexed successfully.")
        sys.exit(0)
    else:
        print("[Restore] Database restoration failed.")
        sys.exit(1)

if __name__ == "__main__":
    main()
