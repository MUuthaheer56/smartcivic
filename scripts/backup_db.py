"""
SmartCivic+ — Database Backup Utility
Exports collections to JSON, compresses them to zip, and rotates old backups.
"""
import os
import zipfile
import json
from datetime import datetime, timedelta
from bson import json_util
from pymongo import MongoClient

def run_backup():
    mongo_uri = os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017/smartcivic")
    client = MongoClient(mongo_uri)
    db = client.get_database()
    
    # 1. Create backups directory if not exists
    backups_dir = os.path.join(os.getcwd(), 'backups')
    os.makedirs(backups_dir, exist_ok=True)
    
    now_str = datetime.utcnow().strftime("%Y-%m-%d_%H-%M")
    temp_backup_dir = os.path.join(backups_dir, f"smartcivic_{now_str}")
    os.makedirs(temp_backup_dir, exist_ok=True)
    
    print(f"[Backup] Exporting collections from '{db.name}'...")
    
    collections = db.list_collection_names()
    for col_name in collections:
        if col_name.startswith("system."):
            continue
        data = list(db[col_name].find())
        file_path = os.path.join(temp_backup_dir, f"{col_name}.json")
        with open(file_path, 'w', encoding='utf-8') as f:
            # Use bson.json_util to preserve ObjectIDs and Datetimes
            f.write(json_util.dumps(data, indent=2))
            
    # 2. Compress backup folder to .zip
    zip_path = os.path.join(backups_dir, f"smartcivic_{now_str}.zip")
    print(f"[Backup] Compressing backup to {zip_path}...")
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(temp_backup_dir):
            for file in files:
                file_full_path = os.path.join(root, file)
                # Save relative path inside zip
                zipf.write(file_full_path, os.path.relpath(file_full_path, backups_dir))
                
    # 3. Clean up temp backup folder
    for file in os.listdir(temp_backup_dir):
        os.remove(os.path.join(temp_backup_dir, file))
    os.rmdir(temp_backup_dir)
    
    # 4. Rotate old backups (delete older than 7 days)
    limit_dt = datetime.utcnow() - timedelta(days=7)
    print("[Backup] Cleaning up backups older than 7 days...")
    for file in os.listdir(backups_dir):
        if file.endswith(".zip") and file.startswith("smartcivic_"):
            try:
                # File format: smartcivic_YYYY-MM-DD_HH-MM.zip
                parts = file.replace("smartcivic_", "").replace(".zip", "").split("_")
                file_dt = datetime.strptime(parts[0], "%Y-%m-%d")
                if file_dt < limit_dt:
                    print(f"[Backup] Deleting old backup file: {file}")
                    os.remove(os.path.join(backups_dir, file))
            except Exception as parse_err:
                print(f"[Backup] Skip rotating file {file}: {parse_err}")
                
    print("[Backup] Backup sweep completed successfully.")

def run_restore(backup_file_name: str):
    """
    Restores the database from a zip backup.
    Requires manual invocation with verification.
    """
    backups_dir = os.path.join(os.getcwd(), 'backups')
    zip_path = os.path.join(backups_dir, backup_file_name)
    if not os.path.exists(zip_path):
        print(f"[Restore] Backup file not found: {zip_path}")
        return False
        
    mongo_uri = os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017/smartcivic")
    client = MongoClient(mongo_uri)
    db = client.get_database()
    
    temp_restore_dir = os.path.join(backups_dir, "temp_restore")
    os.makedirs(temp_restore_dir, exist_ok=True)
    
    with zipfile.ZipFile(zip_path, 'r') as zipf:
        zipf.extractall(backups_dir)
        
    # Find extracted folder name
    # Folder is named e.g. smartcivic_YYYY-MM-DD_HH-MM
    folder_name = backup_file_name.replace(".zip", "")
    extracted_dir = os.path.join(backups_dir, folder_name)
    
    if not os.path.exists(extracted_dir):
        print("[Restore] Extracted backup directory not found.")
        return False
        
    print(f"[Restore] Restoring database collections...")
    for file in os.listdir(extracted_dir):
        if file.endswith(".json"):
            col_name = file.replace(".json", "")
            with open(os.path.join(extracted_dir, file), 'r', encoding='utf-8') as f:
                documents = json_util.loads(f.read())
            # Drop old collection and insert restored docs
            db[col_name].drop()
            if documents:
                db[col_name].insert_many(documents)
            print(f"[Restore] Collection '{col_name}' restored successfully ({len(documents)} docs).")
            
    # Clean up extracted files
    for file in os.listdir(extracted_dir):
        os.remove(os.path.join(extracted_dir, file))
    os.rmdir(extracted_dir)
    
    print("[Restore] Database restoration successfully completed.")
    return True

if __name__ == '__main__':
    run_backup()
