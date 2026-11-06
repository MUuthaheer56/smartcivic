"""
scripts/seed_demo.py - Deterministic Demo Seeder for SmartCivic
Seeds realistic demo data (users across roles, 27 Bangalore wards, ~80 realistic issues across statuses with photos).
Guards: Runs only in dev/test environment (APP_ENV != 'production').
Supports --dry-run flag.
"""

import os
import sys
import argparse
import random
from datetime import datetime, timedelta
from bson import ObjectId
from pymongo import MongoClient

# Add root directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from routes.auth import hash_password
from constants.states import STATUSES


BANGALORE_WARDS = [
    "Ward 1 - Kempegowda Ward", "Ward 2 - Chowdeshwari", "Ward 3 - Atturu", "Ward 4 - Yelahanka Satellite Town",
    "Ward 5 - Jakkuru", "Ward 6 - Thanisandra", "Ward 7 - Byatarayanapura", "Ward 8 - Kodigehalli",
    "Ward 9 - Vidyaranyapura", "Ward 10 - Kuvempu Nagar", "Ward 11 - Jalahalli", "Ward 12 - Shettihalli",
    "Ward 13 - Mallasandra", "Ward 14 - Bagalakunte", "Ward 15 - T Dasarahalli", "Ward 16 - Chokkasandra",
    "Ward 17 - Peenya Industrial Area", "Ward 18 - Rajagopal Nagar", "Ward 19 - Hegganahalli",
    "Ward 110 - Sampangiram Nagar", "Ward 111 - Shantala Nagar", "Ward 112 - Domlur", "Ward 150 - Bellandur",
    "Ward 151 - Koramangala", "Ward 152 - HSR Layout", "Ward 174 - HSR Layout South", "Ward 176 - BTM Layout"
]

DEMO_USERS = [
    {"name": "System Administrator", "email": "admin@smartcivic.com", "role": "admin", "ward": "ALL", "verified": True},
    {"name": "Central Authority", "email": "authority@smartcivic.com", "role": "officer", "ward": "ALL", "verified": True},
    {"name": "Ward 150 Officer", "email": "officer@smartcivic.com", "role": "officer", "ward": "Ward 150 - Bellandur", "verified": True},
    {"name": "Field Worker Ramesh", "email": "worker@smartcivic.com", "role": "worker", "ward": "Ward 150 - Bellandur", "skills": ["road_repair", "pothole", "drainage"], "verified": True, "is_available": True},
    {"name": "Citizen Priya Sharma", "email": "citizen@smartcivic.com", "role": "citizen", "ward": "Ward 150 - Bellandur", "verified": True, "verification_status": "verified"},
    {"name": "Citizen Ananya Rao", "email": "pending_citizen@smartcivic.com", "role": "citizen", "ward": "Ward 151 - Koramangala", "verified": False, "verification_status": "pending"},
]

ISSUE_TEMPLATES = [
    ("road", "pothole", "Large hazardous pothole on 100ft ring road", "critical", "roads"),
    ("road", "crack", "Extensive alligator cracking on inner ward street", "medium", "roads"),
    ("road", "road_surface_damage", "Eroded bitumen surface near metro station exit", "high", "roads"),
    ("sanitation", "garbage_dump", "Overflowing community garbage bin emitting foul odor", "high", "sanitation"),
    ("sanitation", "uncollected_waste", "Uncollected domestic waste pile on sidewalk corner", "medium", "sanitation"),
    ("water", "pipe_leak", "High pressure potable water main burst on main road", "critical", "water_supply"),
    ("water", "low_pressure", "Contaminated muddy water flowing through supply line", "high", "water_supply"),
    ("drainage", "blocked_drain", "Stormwater drain blocked by plastic debris causing road overflow", "high", "drainage"),
    ("electricity", "street_light", "Non-functional street lights along dark junction curve", "medium", "electrical"),
    ("electricity", "hanging_wire", "Low hanging electric cable touching pedestrian walkway", "critical", "electrical"),
]


def seed_database(dry_run: bool = False):
    app_env = os.getenv("APP_ENV", "development").lower()
    if app_env == "production":
        print("[ERROR] seed_demo.py refuses to run in production mode (APP_ENV=production).")
        sys.exit(1)

    mongo_uri = os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017/smartcivic")
    client = MongoClient(mongo_uri)
    db = client.get_database()

    print(f"[*] Connected to DB: {db.name} (dry_run={dry_run})")

    random.seed(42)  # Deterministic seed

    # 1. Prepare Users
    demo_password_hash = hash_password("smartcivic123")
    user_docs = []
    for u in DEMO_USERS:
        doc = dict(u)
        doc["password_hash"] = demo_password_hash
        doc["demo_seed"] = True
        doc["updated_at"] = datetime.utcnow()
        doc["created_at"] = datetime.utcnow() - timedelta(days=30)
        user_docs.append(doc)

    # 2. Prepare Issues (~80 issues across 27 wards and statuses)
    statuses = ["submitted", "ai_reviewed", "assigned", "work_completed", "resolved", "closed"]
    status_weights = [15, 15, 20, 10, 10, 10]  # Sum = 80
    status_pool = []
    for s, count in zip(statuses, status_weights):
        status_pool.extend([s] * count)
    random.shuffle(status_pool)

    # Base coords for Bangalore (Lat 12.91 - 13.05, Lon 77.55 - 77.70)
    issue_docs = []
    now = datetime.utcnow()

    for idx, status in enumerate(status_pool):
        tmpl = ISSUE_TEMPLATES[idx % len(ISSUE_TEMPLATES)]
        cat, is_type, title, sev, dept = tmpl
        ward = BANGALORE_WARDS[idx % len(BANGALORE_WARDS)]

        lat = 12.9200 + (idx * 0.0017) % 0.12
        lon = 77.5800 + (idx * 0.0019) % 0.12

        created_days_ago = random.randint(1, 20)
        created_time = now - timedelta(days=created_days_ago, hours=random.randint(1, 12))

        # Synthetic sample images
        img_url = f"/static/uploads/demo_{cat}_{idx % 4 + 1}.jpg"

        doc = {
            "title": f"{title} - #{idx+1}",
            "description": f"{title}. Observed near landmark point {idx+1}. Needs departmental action.",
            "category": cat,
            "type": is_type,
            "severity": sev,
            "department": dept,
            "ward": ward,
            "status": status,
            "priority": "P0" if sev == "critical" else ("P1" if sev == "high" else "P2"),
            "priority_score": 90.0 if sev == "critical" else (72.0 if sev == "high" else 45.0),
            "location": {
                "type": "Point",
                "coordinates": [round(lon, 6), round(lat, 6)],
                "address": f"Near Landmark {idx+1}, {ward}, Bengaluru"
            },
            "images": [
                {"filename": f"demo_{cat}_{idx+1}.jpg", "url": img_url, "type": "before"}
            ],
            "support_count": random.randint(0, 15),
            "confirmation_count": random.randint(0, 8),
            "demo_seed": True,
            "created_at": created_time,
            "updated_at": created_time + timedelta(hours=random.randint(1, 24))
        }
        issue_docs.append(doc)

    if dry_run:
        print(f"[DRY-RUN] Would upsert {len(user_docs)} demo users.")
        print(f"[DRY-RUN] Would insert {len(issue_docs)} synthetic issues across {len(BANGALORE_WARDS)} wards.")
        print("[DRY-RUN] Dry run complete. No modifications made to database.")
        return

    # Execute DB operations
    print("[*] Upserting demo users...")
    for u in user_docs:
        email = u["email"]
        db.users.update_one({"email": email}, {"$set": u}, upsert=True)

    print("[*] Cleaning previous demo_seed issues...")
    deleted = db.issues.delete_many({"demo_seed": True})
    print(f"[*] Deleted {deleted.deleted_count} old demo issues.")

    print(f"[*] Inserting {len(issue_docs)} new demo issues...")
    inserted = db.issues.insert_many(issue_docs)
    print(f"[SUCCESS] Successfully seeded {len(user_docs)} demo users and {len(inserted.inserted_ids)} issues.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deterministic Demo Seeder for SmartCivic")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without modifying database")
    args = parser.parse_args()
    seed_database(dry_run=args.dry_run)

