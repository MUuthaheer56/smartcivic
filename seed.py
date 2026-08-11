import os
import bcrypt
from datetime import datetime, timedelta
from pymongo import MongoClient
from bson import ObjectId

def hash_password(plain_text: str) -> str:
    return bcrypt.hashpw(plain_text.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def seed_database():
    mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
    db_name = os.getenv('DB_NAME', 'smartcivic')
    
    print(f"Connecting to MongoDB at {mongo_uri} (DB: {db_name})...")
    client = MongoClient(mongo_uri)
    db = client[db_name]
    
    # Clean up existing collections
    print("Clearing existing collections...")
    db.users.drop()
    db.communities.drop()
    db.issues.drop()
    db.votes.drop()
    db.routes.drop()
    db.notifications.drop()
    db.announcements.drop()
    
    # 1. Create Community
    print("Seeding communities...")
    now = datetime.utcnow()
    community_doc = {
        "_id": ObjectId("660000000000000000000001"),
        "name": "TC Palya & KR Puram Ward",
        "city": "Bengaluru",
        "state": "Karnataka",
        "lat": 13.0245,
        "lng": 77.6965,
        "boundary_radius_km": 4.0,
        "community_score": 90,
        "total_issues": 3,
        "resolved_issues": 1,
        "open_issues": 2,
        "created_at": now,
        "score_history": [
            {"score": 100, "change": 0, "reason": "Initial Score", "timestamp": now - timedelta(days=5)},
            {"score": 98, "change": -2, "reason": "New pothole issue", "timestamp": now - timedelta(days=4)},
            {"score": 95, "change": -3, "reason": "SLA Breach on garbage pile", "timestamp": now - timedelta(days=3)},
            {"score": 90, "change": -5, "reason": "Severe drainage issue reported", "timestamp": now - timedelta(days=2)},
            {"score": 95, "change": 5, "reason": "Resolved broken street light", "timestamp": now - timedelta(days=1)}
        ]
    }
    db.communities.insert_one(community_doc)
    
    # 2. Create Users
    print("Seeding users (password: 'smartcivic123')...")
    pwd_hash = hash_password("smartcivic123")
    
    users = [
        {
            "_id": ObjectId("660000000000000000000002"),
            "name": "Arjun Gowda (Authority)",
            "email": "authority@smartcivic.com",
            "password_hash": pwd_hash,
            "role": "authority",
            "community_id": ObjectId("660000000000000000000001"),
            "is_verified": True,
            "verification_doc": None,
            "created_at": now,
            "last_login": now,
            "reports_count": 0,
            "votes_count": 0,
            "issues_resolved_count": 0,
            "reputation_score": 0,
            "reputation_tier": "Newcomer",
            "is_anonymous_by_default": False,
            "last_lat": None,
            "last_lng": None,
            "onboarding_complete": True,
            "preferred_language": "en"
        },
        {
            "_id": ObjectId("660000000000000000000003"),
            "name": "Sunita Rao (Resident)",
            "email": "resident@smartcivic.com",
            "password_hash": pwd_hash,
            "role": "resident",
            "community_id": ObjectId("660000000000000000000001"),
            "is_verified": True,
            "verification_doc": None,
            "created_at": now,
            "last_login": now,
            "reports_count": 3,
            "votes_count": 10,
            "issues_resolved_count": 1,
            "reputation_score": 35,
            "reputation_tier": "Active Resident",
            "is_anonymous_by_default": False,
            "last_lat": None,
            "last_lng": None,
            "onboarding_complete": True,
            "preferred_language": "en"
        },
        {
            "_id": ObjectId("660000000000000000000004"),
            "name": "Ramesh Kumar (Field Worker)",
            "email": "worker@smartcivic.com",
            "password_hash": pwd_hash,
            "role": "field_worker",
            "community_id": ObjectId("660000000000000000000001"),
            "is_verified": True,
            "verification_doc": None,
            "created_at": now,
            "last_login": now,
            "reports_count": 0,
            "votes_count": 0,
            "issues_resolved_count": 5,
            "reputation_score": 50,
            "reputation_tier": "Civic Champion",
            "is_anonymous_by_default": False,
            "last_lat": 13.0245,
            "last_lng": 77.6965,
            "onboarding_complete": True,
            "preferred_language": "en"
        },
        {
            "_id": ObjectId("660000000000000000000020"),
            "name": "Suresh Gowda (Pending Verification)",
            "email": "pending@smartcivic.com",
            "password_hash": pwd_hash,
            "role": "resident",
            "community_id": ObjectId("660000000000000000000001"),
            "is_verified": False,
            "verification_doc": "static/uploads/docs/mock_doc.jpg",
            "created_at": now,
            "last_login": now,
            "reports_count": 0,
            "votes_count": 0,
            "issues_resolved_count": 0,
            "reputation_score": 0,
            "reputation_tier": "Newcomer",
            "is_anonymous_by_default": False,
            "last_lat": None,
            "last_lng": None,
            "onboarding_complete": False,
            "preferred_language": "en"
        }
    ]
    db.users.insert_many(users)
    
    # 3. Create Sample Issues
    print("Seeding issues...")
    issues = [
        {
            "_id": ObjectId("660000000000000000000005"),
            "title": "Severe Pothole on TC Palya Main Road",
            "description": "Massive crater in the middle of the road causing traffic slowdowns near the bus stop.",
            "category": "pothole",
            "images": [],
            "lat": 13.0298,
            "lng": 77.6948,
            "address": "TC Palya Junction, Road Side",
            "community_id": ObjectId("660000000000000000000001"),
            "reporter_id": ObjectId("660000000000000000000003"),
            "is_anonymous": False,
            "status": "pending_validation",
            "severity": 3,
            "severity_override": None,
            "severity_override_by": None,
            "confirm_votes": 2,
            "deny_votes": 0,
            "severity_votes": [3, 4],
            "upvotes": 5,
            "upvoted_by": [],
            "linked_issue_ids": [],
            "validated_at": None,
            "assigned_to": None,
            "assigned_at": None,
            "resolved_at": None,
            "resolution_note": None,
            "resolution_image": None,
            "created_at": now - timedelta(hours=6),
            "sla_deadline": now + timedelta(days=7),
            "sla_breached": False,
            "stale_3days_applied": False,
            "stale_7days_applied": False,
            "comments": [
                {
                    "user_id": ObjectId("660000000000000000000002"),
                    "name": "Arjun Gowda (Authority)",
                    "text": "Checking with road works division.",
                    "timestamp": now - timedelta(hours=4)
                }
            ],
            "status_history": [
                {"status": "pending_validation", "changed_by": ObjectId("660000000000000000000003"), "timestamp": now - timedelta(hours=6), "note": "Issue reported."}
            ]
        },
        {
            "_id": ObjectId("660000000000000000000006"),
            "title": "Overflowing Garbage Dumpster near Varanasi Cross",
            "description": "Garbage has accumulated at the corner, creating an unhygienic environment and blocking the sidewalk.",
            "category": "garbage",
            "images": [],
            "lat": 13.0358,
            "lng": 77.7001,
            "address": "Varanasi Cross Main Road",
            "community_id": ObjectId("660000000000000000000001"),
            "reporter_id": ObjectId("660000000000000000000003"),
            "is_anonymous": True,
            "status": "validated",
            "severity": 4,
            "severity_override": None,
            "severity_override_by": None,
            "confirm_votes": 3,
            "deny_votes": 0,
            "severity_votes": [4, 4, 5],
            "upvotes": 12,
            "upvoted_by": [],
            "linked_issue_ids": [],
            "validated_at": now - timedelta(days=1),
            "assigned_to": None,
            "assigned_at": None,
            "resolved_at": None,
            "resolution_note": None,
            "resolution_image": None,
            "created_at": now - timedelta(days=2),
            "sla_deadline": now + timedelta(hours=12),
            "sla_breached": False,
            "stale_3days_applied": False,
            "stale_7days_applied": False,
            "comments": [],
            "status_history": [
                {"status": "pending_validation", "changed_by": ObjectId("660000000000000000000003"), "timestamp": now - timedelta(days=2), "note": "Issue reported."},
                {"status": "validated", "changed_by": None, "timestamp": now - timedelta(days=1), "note": "Validated by community votes."}
            ]
        },
        {
            "_id": ObjectId("660000000000000000000007"),
            "title": "Broken Street Light in Babusahibpalya Lane 3",
            "description": "The street lamp has fused, leaving the lane dark and unsafe.",
            "category": "streetlight",
            "images": [],
            "lat": 13.0232,
            "lng": 77.6823,
            "address": "Babu Sahib Palya Road, Lane 3",
            "community_id": ObjectId("660000000000000000000001"),
            "reporter_id": ObjectId("660000000000000000000003"),
            "is_anonymous": False,
            "status": "resolved",
            "severity": 2,
            "severity_override": None,
            "severity_override_by": None,
            "confirm_votes": 3,
            "deny_votes": 0,
            "severity_votes": [2, 2, 3],
            "upvotes": 2,
            "upvoted_by": [],
            "linked_issue_ids": [],
            "validated_at": now - timedelta(days=4),
            "assigned_to": ObjectId("660000000000000000000004"),
            "assigned_at": now - timedelta(days=3),
            "resolved_at": now - timedelta(days=1),
            "resolution_note": "Replaced the fused LED bulb and fixed structural wiring.",
            "resolution_image": None,
            "created_at": now - timedelta(days=5),
            "sla_deadline": now - timedelta(days=2),
            "sla_breached": False,
            "stale_3days_applied": False,
            "stale_7days_applied": False,
            "comments": [],
            "status_history": [
                {"status": "pending_validation", "changed_by": ObjectId("660000000000000000000003"), "timestamp": now - timedelta(days=5), "note": "Issue reported."},
                {"status": "validated", "changed_by": None, "timestamp": now - timedelta(days=4), "note": "Validated by community votes."},
                {"status": "assigned", "changed_by": ObjectId("660000000000000000000002"), "timestamp": now - timedelta(days=3), "note": "Assigned to worker Ramesh."},
                {"status": "resolved", "changed_by": ObjectId("660000000000000000000004"), "timestamp": now - timedelta(days=1), "note": "Fixed street lamp bulb."}
            ]
        }
    ]
    db.issues.insert_many(issues)
    
    # 4. Announcements
    print("Seeding announcements...")
    ann = {
        "title": "Water Shutdown Notice",
        "body": "BWSSB maintenance on local pipes will lead to no water supply on Wednesday between 9 AM and 4 PM. Please store water accordingly.",
        "community_id": ObjectId("660000000000000000000001"),
        "created_by": ObjectId("660000000000000000000002"),
        "created_at": now - timedelta(hours=2),
        "expires_at": now + timedelta(days=2),
        "is_active": True
    }
    db.announcements.insert_one(ann)
    
    # Create indexes explicitly just to verify indices are set correctly
    db.users.create_index('email', unique=True)
    db.votes.create_index([('issue_id', 1), ('voter_id', 1)], unique=True)
    
    print("Database seeding completed successfully!")

if __name__ == '__main__':
    # Load dotenv if available
    from dotenv import load_dotenv
    load_dotenv()
    seed_database()
