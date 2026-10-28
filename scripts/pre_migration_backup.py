"""
SmartCivic+ — Pre-Migration Backup Script
Takes complete snapshot of MongoDB database and static/uploads folder before any destructive operations.
"""
import os
import zipfile
from scripts.backup_db import run_backup

def backup_all():
    print("=== STARTING FULL PRE-MIGRATION BACKUP ===")
    # 1. Run database backup
    run_backup()

    # 2. Archive static/uploads if present
    backups_dir = os.path.join(os.getcwd(), 'backups')
    os.makedirs(backups_dir, exist_ok=True)
    uploads_src = os.path.join(os.getcwd(), 'static', 'uploads')
    
    if os.path.exists(uploads_src):
        zip_dst = os.path.join(backups_dir, 'static_uploads_archive.zip')
        print(f"[Backup] Archiving {uploads_src} to {zip_dst}...")
        with zipfile.ZipFile(zip_dst, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(uploads_src):
                for file in files:
                    full_p = os.path.join(root, file)
                    rel_p = os.path.relpath(full_p, uploads_src)
                    zipf.write(full_p, rel_p)
        print(f"[Backup] static/uploads archived successfully ({os.path.getsize(zip_dst)} bytes).")
    else:
        print("[Backup] static/uploads does not exist; skipping folder archive.")

    print("=== BACKUP COMPLETE ===")

if __name__ == "__main__":
    backup_all()
