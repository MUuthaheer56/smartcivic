"""
SmartCivic+ — Database Seeder Script
"""
from pymongo import MongoClient
from datetime import datetime
import bcrypt

def hash_password(plain_text: str) -> str:
    return bcrypt.hashpw(plain_text.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def seed_db():
    client = MongoClient("mongodb://localhost:27017/")
    db = client.smartcivic
    
    print("Clearing legacy database collections...")
    db.users.drop()
    db.issues.drop()
    db.clusters.drop()
    db.assignments.drop()
    db.notifications.drop()
    db.audit_logs.drop()
    
    pwd_hash = hash_password("smartcivic123")
    
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
    
    db.users.insert_many(users)
    print("Database seeded successfully with SmartCivic+ credentials (password: 'smartcivic123').")

if __name__ == '__main__':
    seed_db()
