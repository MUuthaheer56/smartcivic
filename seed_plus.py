"""
SmartCivic+ — Database Seeder Script
"""
from pymongo import MongoClient
from datetime import datetime
import bcrypt

def hash_password(plain_text: str) -> str:
    return bcrypt.hashpw(plain_text.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def seed_db():
    client = MongoClient("mongodb://127.0.0.1:27017/")
    db = client.smartcivic
    
    print("Clearing legacy database collections...")
    db.users.drop()
    db.issues.drop()
    db.clusters.drop()
    db.assignments.drop()
    db.notifications.drop()
    db.audit_logs.drop()
    
    import secrets
    plain_password = secrets.token_urlsafe(12)
    pwd_hash = hash_password(plain_password)
    
    with open("seed_credentials.txt", "w", encoding="utf-8") as f:
        f.write(f"SEED_PASSWORD={plain_password}\n")
    print("[Seeder] Credentials generated and written to seed_credentials.txt")
    
    print("Seeding new SmartCivic+ user profiles...")
    users = [
        # Citizens
        {
            "name": "Resident Citizen",
            "email": "citizen@smartcivic.com",
            "password_hash": pwd_hash,
            "role": "citizen",
            "ward": "Ward 1",
            "civic_score": 100,
            "role_tier": "verifier",
            "reports_submitted": 0,
            "reports_verified_accurate": 0,
            "created_at": datetime.utcnow(),
            "last_login": None
        },
        # Officers
        {
            "name": "Ward Officer 1",
            "email": "officer@smartcivic.com",
            "password_hash": pwd_hash,
            "role": "officer",
            "ward": "Ward 1",
            "created_at": datetime.utcnow(),
            "last_login": None
        },
        {
            "name": "Central Authority",
            "email": "authority@smartcivic.com",
            "password_hash": pwd_hash,
            "role": "officer",
            "ward": "all",
            "created_at": datetime.utcnow(),
            "last_login": None
        },
        # Workers
        {
            "name": "Road Repair Crew",
            "email": "worker@smartcivic.com",
            "password_hash": pwd_hash,
            "role": "worker",
            "ward": "Ward 1",
            "skills": ["road_repair", "roads", "road"],
            "current_location": {
                "type": "Point",
                "coordinates": [77.5946, 12.9716]
            },
            "active_assignments": 0,
            "is_available": True,
            "created_at": datetime.utcnow(),
            "last_login": None
        },
        {
            "name": "Electrical Crew",
            "email": "worker2@smartcivic.com",
            "password_hash": pwd_hash,
            "role": "worker",
            "ward": "Ward 1",
            "skills": ["electrical", "electricity"],
            "current_location": {
                "type": "Point",
                "coordinates": [77.5996, 12.9756]
            },
            "active_assignments": 0,
            "is_available": True,
            "created_at": datetime.utcnow(),
            "last_login": None
        }
    ]
    
    res = db.users.insert_many(users)
    citizen_user = db.users.find_one({"role": "citizen"})
    worker_user = db.users.find_one({"role": "worker"})
    citizen_id = citizen_user["_id"] if citizen_user else None
    worker_id = worker_user["_id"] if worker_user else None

    print("Seeding realistic civic complaint issues across categories & statuses...")
    from datetime import timedelta
    now = datetime.utcnow()
    
    issues = [
        {
            "title": "Severe Pothole on MG Road Junction",
            "description": "Massive crater on MG road causing traffic congestion and tire damage.",
            "category": "road",
            "type": "pothole",
            "severity": "critical",
            "department": "roads",
            "status": "ai_reviewed",
            "ward": "Ward 1",
            "address": "MG Road Junction, Ward 1",
            "location": {"type": "Point", "coordinates": [77.5946, 12.9716]},
            "citizen_id": citizen_id,
            "priority_score": 88.5,
            "created_at": now - timedelta(hours=4),
            "sla_deadline": now + timedelta(hours=8),
            "sla_status": "on_track",
            "confirmation_count": 5
        },
        {
            "title": "Major Pipe Leakage near Central Park",
            "description": "Water gushing out of broken main line, flooding sidewalk.",
            "category": "water",
            "type": "pipe_leakage",
            "severity": "high",
            "department": "water_supply",
            "status": "officer_reviewed",
            "ward": "Ward 1",
            "address": "Central Park East Gate, Ward 1",
            "location": {"type": "Point", "coordinates": [77.5986, 12.9736]},
            "citizen_id": citizen_id,
            "priority_score": 72.0,
            "created_at": now - timedelta(hours=10),
            "sla_deadline": now + timedelta(hours=14),
            "sla_status": "on_track",
            "confirmation_count": 3
        },
        {
            "title": "Hanging Live Electric Wire Near School",
            "description": "Loose high voltage cable dangling near primary school gate. Extremely dangerous.",
            "category": "electricity",
            "type": "live_wire",
            "severity": "critical",
            "department": "electrical",
            "status": "work_started",
            "ward": "Ward 1",
            "address": "St. Joseph School Lane, Ward 1",
            "location": {"type": "Point", "coordinates": [77.5996, 12.9756]},
            "citizen_id": citizen_id,
            "worker_id": worker_id,
            "is_emergency": True,
            "emergency_category": "ELECTRICAL_DANGER",
            "priority_score": 98.0,
            "created_at": now - timedelta(hours=2),
            "sla_deadline": now + timedelta(hours=2),
            "sla_status": "urgent",
            "confirmation_count": 12
        },
        {
            "title": "Overflowing Garbage Dump at Market Square",
            "description": "Garbage has not been collected for 3 days, foul odor spreading.",
            "category": "sanitation",
            "type": "garbage_dump",
            "severity": "medium",
            "department": "sanitation",
            "status": "assigned",
            "ward": "Ward 1",
            "address": "Market Square Block B, Ward 1",
            "location": {"type": "Point", "coordinates": [77.5926, 12.9696]},
            "citizen_id": citizen_id,
            "worker_id": worker_id,
            "priority_score": 55.0,
            "created_at": now - timedelta(hours=18),
            "sla_deadline": now + timedelta(hours=6),
            "sla_status": "warning",
            "confirmation_count": 2
        },
        {
            "title": "Blocked Storm Drain Cause Flooding",
            "description": "Storm drain clogged with plastic waste causing rainwater pooling.",
            "category": "drainage",
            "type": "drain_overflow",
            "severity": "high",
            "department": "drainage",
            "status": "work_completed",
            "ward": "Ward 1",
            "address": "Suburban Layout 4th Cross, Ward 1",
            "location": {"type": "Point", "coordinates": [77.6016, 12.9786]},
            "citizen_id": citizen_id,
            "worker_id": worker_id,
            "priority_score": 65.0,
            "created_at": now - timedelta(hours=24),
            "sla_deadline": now - timedelta(hours=2),
            "sla_status": "breached",
            "confirmation_count": 4
        },
        {
            "title": "Loud Construction Generator at Night",
            "description": "Unpermitted commercial generator operating past midnight causing severe noise pollution.",
            "category": "noise",
            "type": "noise_violation",
            "severity": "low",
            "department": "roads",
            "status": "closed",
            "ward": "Ward 1",
            "address": "Commercial Enclave Road 2, Ward 1",
            "location": {"type": "Point", "coordinates": [77.5906, 12.9676]},
            "citizen_id": citizen_id,
            "priority_score": 25.0,
            "created_at": now - timedelta(days=2),
            "sla_deadline": now - timedelta(days=1),
            "sla_status": "on_track",
            "confirmation_count": 1
        },
        {
            "title": "Broken Footpath Concrete Slab",
            "description": "Damaged pedestrian walkway slab causing tripping hazard.",
            "category": "other",
            "type": "footpath_damage",
            "severity": "low",
            "department": "roads",
            "status": "submitted",
            "ward": "Ward 1",
            "address": "Residential Avenue 8th Main, Ward 1",
            "location": {"type": "Point", "coordinates": [77.5956, 12.9726]},
            "citizen_id": citizen_id,
            "priority_score": 30.0,
            "created_at": now - timedelta(hours=1),
            "sla_deadline": now + timedelta(hours=47),
            "sla_status": "on_track",
            "confirmation_count": 0
        }
    ]
    
    db.issues.insert_many(issues)
    print("Database seeded successfully with SmartCivic+ user credentials and sample issues.")

if __name__ == '__main__':
    seed_db()

