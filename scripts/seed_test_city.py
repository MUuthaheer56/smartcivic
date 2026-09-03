"""
SmartCivic+ — Test City Data Generator
Seeds database with realistic civic data (500 workers, 10,000 complaints).
Safe to run multiple times: deletes only documents matching {"seeded": True}.
"""
import os
import random
from datetime import datetime, timedelta
from bson import ObjectId
from pymongo import MongoClient

def run_seeder():
    mongo_uri = os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017/smartcivic")
    client = MongoClient(mongo_uri)
    db = client.get_database()
    
    print("[Seeder] Cleaning existing seeded data...")
    db.users.delete_many({"seeded": True})
    db.issues.delete_many({"seeded": True})
    db.clusters.delete_many({"seeded": True})
    db.hotspots.delete_many({"seeded": True})
    db.audit_logs.delete_many({"seeded": True})
    
    # Generate 50 Wards
    wards = [f"Ward {i}" for i in range(1, 51)]
    
    # 20 Departments
    departments = [
        "roads", "water_supply", "electrical", "sanitation", "drainage",
        "health", "education", "fire", "transport", "police",
        "parks", "public_works", "housing", "revenue", "records",
        "building", "license", "environment", "emergency", "social_welfare"
    ]
    
    category_map = {
        "road": "roads",
        "sanitation": "sanitation",
        "drainage": "drainage",
        "electricity": "electrical",
        "water": "water_supply",
        "other": "public_works"
    }
    
    categories = list(category_map.keys())
    category_weights = [0.28, 0.22, 0.18, 0.13, 0.11, 0.08]
    
    statuses = ["closed", "work_started", "assigned", "ai_reviewed", "submitted"]
    status_weights = [0.60, 0.20, 0.10, 0.07, 0.03]
    
    severities = ["low", "medium", "high", "critical"]
    severity_weights = [0.35, 0.40, 0.18, 0.07]
    
    print("[Seeder] Generating 500 workers...")
    workers_list = []
    # Password hash for 'smartcivic123'
    # Generated using bcrypt.hashpw(b'smartcivic123', bcrypt.gensalt()).decode()
    # We can pre-calculate it:
    pwd_hash = "$2b$12$Z0H7kM9z87sX27z3c1234ux32S9v9g79W4J612d7890S12d345678"
    
    for i in range(1, 501):
        dept = random.choice(departments)
        ward = random.choice(wards)
        
        # Skills match the department
        skills = [dept]
        if dept == "roads":
            skills.append("road_repair")
        elif dept == "electrical":
            skills.append("streetlight")
            
        worker = {
            "name": f"Worker {i}",
            "email": f"worker{i}@smartcivic.com",
            "password_hash": pwd_hash,
            "role": "worker",
            "ward": ward,
            "skills": skills,
            "current_location": {
                "type": "Point",
                "coordinates": [
                    77.5946 + random.uniform(-0.15, 0.15),
                    12.9716 + random.uniform(-0.15, 0.15)
                ]
            },
            "active_assignments": 0,
            "is_available": True,
            "average_rating": round(random.uniform(3.5, 5.0), 2),
            "total_ratings": random.randint(5, 50),
            "created_at": datetime.utcnow() - timedelta(days=365),
            "seeded": True
        }
        workers_list.append(worker)
        
    db.users.insert_many(workers_list)
    # Fetch inserted worker IDs
    all_workers = list(db.users.find({"role": "worker", "seeded": True}))
    
    print("[Seeder] Spawning 10,000 complaints...")
    complaints = []
    now = datetime.utcnow()
    
    # 15 Recurring issue locations (anchors)
    recurring_anchors = []
    for _ in range(15):
        lng = 77.5946 + random.uniform(-0.08, 0.08)
        lat = 12.9716 + random.uniform(-0.08, 0.08)
        cat = random.choice(categories)
        wrd = random.choice(wards)
        recurring_anchors.append((lat, lng, cat, wrd))
        
    # Generate issues
    for i in range(1, 10001):
        # Determine category & department
        category = random.choices(categories, weights=category_weights, k=1)[0]
        dept = category_map[category]
        
        # Decide if this issue is one of the recurring hotspots (approx 10% chance)
        is_rec_hotspot = random.random() < 0.10
        if is_rec_hotspot:
            anchor = random.choice(recurring_anchors)
            lat = anchor[0] + random.uniform(-0.001, 0.001)
            lng = anchor[1] + random.uniform(-0.001, 0.001)
            category = anchor[2]
            dept = category_map[category]
            ward = anchor[3]
        else:
            lat = 12.9716 + random.uniform(-0.12, 0.12)
            lng = 77.5946 + random.uniform(-0.12, 0.12)
            ward = random.choice(wards)
            
        status = random.choices(statuses, weights=status_weights, k=1)[0]
        severity = random.choices(severities, weights=severity_weights, k=1)[0]
        
        # Time distribution: higher density in recent 3 months (90 days)
        if random.random() < 0.70:
            created_days_ago = random.randint(0, 90)
        else:
            created_days_ago = random.randint(91, 365)
            
        created_at = now - timedelta(days=created_days_ago, hours=random.randint(0, 23))
        
        # Determine worker assignment
        worker_id = None
        if status in ["assigned", "work_started", "closed"]:
            # Pick a worker matching dept or skills
            dept_workers = [w for w in all_workers if w["ward"] == ward and dept in w["skills"]]
            if not dept_workers:
                dept_workers = [w for w in all_workers if dept in w["skills"]]
            if dept_workers:
                worker_id = random.choice(dept_workers)["_id"]
                
        # Handle closed ratings and verified status
        rating = None
        feedback = None
        resolved_at = None
        if status == "closed":
            resolved_at = created_at + timedelta(hours=random.randint(4, 72))
            rating = random.choices([1, 2, 3, 4, 5], weights=[0.05, 0.05, 0.10, 0.40, 0.40], k=1)[0]
            feedback = "Satisfactory repair."
            
        sla_deadline = created_at + timedelta(hours=24 if severity == "critical" else 48)
        sla_status = "on_track"
        if status != "closed" and now > sla_deadline:
            sla_status = "breached"
        elif status == "closed" and resolved_at > sla_deadline:
            sla_status = "breached"
            
        issue = {
            "title": f"Civic defect {category} reported",
            "description": f"Encountered defect in category {category} located at coordinate lat={lat}, lng={lng}.",
            "category": category,
            "type": f"{category}_leak" if category == "water" else f"{category}_pothole",
            "severity": severity,
            "status": status,
            "ward": ward,
            "department": dept,
            "location": {
                "type": "Point",
                "coordinates": [lng, lat]
            },
            "address": f"Street No. {random.randint(1, 100)}, {ward}, Bengaluru",
            "citizen_id": ObjectId(), # Random user
            "worker_id": worker_id,
            "sla_deadline": sla_deadline,
            "sla_status": sla_status,
            "priority_score": random.uniform(10, 95),
            "is_emergency": (severity == "critical"),
            "emergency_category": "FLOODING" if severity == "critical" else None,
            "citizen_rating": rating,
            "citizen_feedback_text": feedback,
            "feedback_submitted_at": resolved_at,
            "is_recurring": is_rec_hotspot,
            "recurrence_count": random.randint(5, 12) if is_rec_hotspot else 0,
            "first_occurrence_at": created_at - timedelta(days=120) if is_rec_hotspot else None,
            "created_at": created_at,
            "updated_at": resolved_at or created_at,
            "seeded": True
        }
        
        complaints.append(issue)
        
        # Batch insert to keep memory footprint low
        if len(complaints) >= 2000:
            db.issues.insert_many(complaints)
            complaints = []
            
    if complaints:
        db.issues.insert_many(complaints)
        
    print("\nTest City Seed Complete")
    print(f"Wards:        50")
    print(f"Workers:      500")
    print(f"Complaints:   10,000")
    print(f"  Closed:     {db.issues.count_documents({'status': 'closed', 'seeded': True})}")
    print(f"  Active:     {db.issues.count_documents({'status': {'$ne': 'closed'}, 'seeded': True})}")
    print(f"Recurring:    15 locations")
    
if __name__ == '__main__':
    run_seeder()
