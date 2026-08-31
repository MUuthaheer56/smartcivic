"""
SmartCivic+ — Database Indexes Setup Script
Configures high-performance indexes for complaints routing, maps, and audit logs.
"""
import os
from pymongo import MongoClient

def setup_indexes():
    mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/smartcivic")
    client = MongoClient(mongo_uri)
    db = client.get_database()
    
    print("[Indexes] Creating issues indexes...")
    db.issues.create_index([("status", 1)])
    db.issues.create_index([("ward", 1)])
    db.issues.create_index([("department", 1)])
    db.issues.create_index([("severity", 1)])
    db.issues.create_index([("citizen_id", 1)])
    db.issues.create_index([("worker_id", 1)])
    db.issues.create_index([("created_at", -1)])
    db.issues.create_index([("sla_deadline", 1), ("status", 1)])
    db.issues.create_index([("location", "2dsphere")])  # for geospatial queries
    db.issues.create_index([("priority_score", -1)])
    
    print("[Indexes] Creating audit logs indexes...")
    db.audit_logs.create_index([("entity_id", 1)])
    db.audit_logs.create_index([("timestamp", -1)])
    
    print("[Indexes] Creating notifications indexes...")
    db.notifications.create_index([("recipient_id", 1), ("read", 1)])
    
    print("[Indexes] Creating infrastructure indexes...")
    db.infrastructure.create_index([("segment_id", 1)], unique=True)
    db.infrastructure.create_index([("location", "2dsphere")])
    db.infrastructure.create_index([("health_score", 1)])
    
    print("[Indexes] MongoDB index configurations completed successfully.")

if __name__ == '__main__':
    setup_indexes()
