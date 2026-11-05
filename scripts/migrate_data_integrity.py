"""
SmartCivic — Phase 5 Data Integrity Migration Script
Standardizes:
1. Notifications: guarantees both 'read' and 'is_read' booleans are in sync.
2. Issues: synchronizes 'ward' and 'ward_id' consistency.
3. String to ObjectId references where valid ObjectId strings exist.
Supports dry-run mode (--dry-run).
"""
import sys
import os
from bson import ObjectId
from pymongo import MongoClient

def run_migration(dry_run=True, mongo_uri=None):
    uri = mongo_uri or os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017/smartcivic")
    db_name = uri.split('/')[-1] if '/' in uri else 'smartcivic'
    if not db_name or '?' in db_name or db_name.strip() == '':
        db_name = 'smartcivic'
    client = MongoClient(uri)
    db = client[db_name]

    print(f"=== Running Data Integrity Migration (dry_run={dry_run}) on DB: '{db_name}' ===")

    # 1. Sync notifications read / is_read
    notifs = list(db.notifications.find({}))
    notif_updates = 0
    for n in notifs:
        is_read = n.get("is_read")
        read = n.get("read")
        target_val = is_read if is_read is not None else (read if read is not None else False)
        if is_read != target_val or read != target_val:
            notif_updates += 1
            if not dry_run:
                db.notifications.update_one(
                    {"_id": n["_id"]},
                    {"$set": {"read": target_val, "is_read": target_val}}
                )
    print(f"[Notifications] Synchronized {notif_updates} notification records (read == is_read).")

    # 2. Sync issues ward and ward_id
    issues = list(db.issues.find({}))
    issue_updates = 0
    for iss in issues:
        w = iss.get("ward")
        w_id = iss.get("ward_id")
        updates = {}
        if w and not w_id:
            updates["ward_id"] = str(w)
        elif w_id and not w:
            updates["ward"] = str(w_id)
        if updates:
            issue_updates += 1
            if not dry_run:
                db.issues.update_one({"_id": iss["_id"]}, {"$set": updates})
    print(f"[Issues] Synchronized {issue_updates} issue records (ward <-> ward_id).")

    # 3. Standardize citizen_id as ObjectId in issues
    type_conversions = 0
    for iss in issues:
        cit_id = iss.get("citizen_id")
        if isinstance(cit_id, str) and ObjectId.is_valid(cit_id):
            type_conversions += 1
            if not dry_run:
                db.issues.update_one({"_id": iss["_id"]}, {"$set": {"citizen_id": ObjectId(cit_id)}})
    print(f"[Issues] Converted {type_conversions} string citizen_ids to ObjectIds.")

    print(f"=== Migration complete. Mode: {'DRY RUN (no writes performed)' if dry_run else 'APPLIED'} ===")
    return {
        "notif_updates": notif_updates,
        "issue_updates": issue_updates,
        "type_conversions": type_conversions
    }

if __name__ == "__main__":
    is_dry = "--apply" not in sys.argv
    run_migration(dry_run=is_dry)
