"""
SmartCivic — Migration Script: Consolidate db.complaints into canonical db.issues
Copies missing complaint documents into db.issues with normalized field aliases.
Does NOT delete data from db.complaints.
"""
import os
from pymongo import MongoClient
from bson import ObjectId
from datetime import datetime

def migrate():
    mongo_uri = os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017/smartcivic")
    db_name = mongo_uri.split('/')[-1] if '/' in mongo_uri else 'smartcivic'
    if not db_name or db_name.strip() == "" or '?' in db_name:
        db_name = 'smartcivic'
        
    client = MongoClient(mongo_uri)
    db = client[db_name]

    complaints = list(db.complaints.find({}))
    print(f"[Migration] Found {len(complaints)} documents in 'complaints' collection.")

    migrated_count = 0
    for doc in complaints:
        doc_id = doc["_id"]

        # Check if already in db.issues
        existing = db.issues.find_one({"_id": doc_id})
        if not existing:
            # Build normalized canonical issue document from complaint doc
            citizen_id_str = str(doc.get("reporter_id") or doc.get("citizen_id") or "")
            category_val = str(doc.get("service") or doc.get("category") or "other")
            type_val = str(doc.get("issue_type") or doc.get("type") or "other")
            lat = float(doc.get("latitude") or doc.get("lat") or (doc.get("location", {}).get("coordinates", [0, 0])[1] if doc.get("location") else 0))
            lng = float(doc.get("longitude") or doc.get("lng") or (doc.get("location", {}).get("coordinates", [0, 0])[0] if doc.get("location") else 0))
            
            photos_list = doc.get("photos", [])
            images_list = doc.get("images", [])
            if not photos_list and images_list:
                photos_list = [img.get("url") if isinstance(img, dict) else img for img in images_list]

            canonical_doc = {
                "_id": doc_id,
                "issue_id": doc.get("issue_id") or f"SC-{str(doc_id)[-6:].upper()}",
                "title": doc.get("title") or doc.get("description", "Civic Issue")[:50],
                "description": doc.get("description", ""),
                "original_description": doc.get("original_description") or doc.get("description", ""),
                "translated_description": doc.get("translated_description") or doc.get("description", ""),
                "original_language": doc.get("original_language", "english"),
                "category": category_val,
                "service": category_val,
                "type": type_val,
                "issue_type": type_val,
                "severity": doc.get("severity", "medium"),
                "priority": doc.get("priority", "P3"),
                "priority_score": float(doc.get("priority_score", 0.0)),
                "status": str(doc.get("status", "submitted")).lower(),
                "emergency": bool(doc.get("emergency") or doc.get("is_emergency")),
                "is_emergency": bool(doc.get("emergency") or doc.get("is_emergency")),
                "emergency_state": doc.get("emergency_state"),
                "location": {
                    "type": "Point",
                    "coordinates": [lng, lat]
                },
                "address": doc.get("address", doc.get("location_text", "")),
                "latitude": lat,
                "longitude": lng,
                "location_text": doc.get("location_text", doc.get("address", "")),
                "location_hints": doc.get("location_hints", []),
                "ward": doc.get("ward", "Ward 1"),
                "ward_id": doc.get("ward_id", "ward_1"),
                "department": doc.get("department", "roads"),
                "citizen_id": ObjectId(citizen_id_str) if ObjectId.is_valid(citizen_id_str) else None,
                "reporter_id": citizen_id_str,
                "reporter_verified": bool(doc.get("reporter_verified")),
                "officer_id": doc.get("officer_id") or doc.get("assigned_officer_id"),
                "assigned_officer_id": doc.get("assigned_officer_id") or doc.get("officer_id"),
                "worker_id": doc.get("worker_id"),
                "ai_confidence": float(doc.get("ai_confidence") or 0.0),
                "ai_route_decision": doc.get("ai_route_decision"),
                "ai_analysis": doc.get("ai_analysis") or {},
                "impact": doc.get("impact") or {},
                "supporters": doc.get("supporters") or [],
                "support_count": int(doc.get("support_count") or len(doc.get("supporters") or [])),
                "verification_status": doc.get("verification_status") or "PENDING",
                "confidence_score": float(doc.get("confidence_score") or 0.0),
                "authority_primary": doc.get("authority_primary"),
                "authority_secondary": doc.get("authority_secondary", []),
                "food_details": doc.get("food_details"),
                "is_multi_issue": bool(doc.get("is_multi_issue")),
                "sub_issues": doc.get("sub_issues", []),
                "parent_id": doc.get("parent_id"),
                "photos": photos_list,
                "images": images_list or [{"url": p, "type": "before"} for p in photos_list],
                "image": doc.get("image") or ({"url": photos_list[0]} if photos_list else None),
                "sla_deadline": doc.get("sla_deadline") or doc.get("created_at") or datetime.utcnow(),
                "sla_status": doc.get("sla_status", "on_track"),
                "status_history": doc.get("status_history", []),
                "created_at": doc.get("created_at", datetime.utcnow()),
                "updated_at": doc.get("updated_at", datetime.utcnow())
            }

            db.issues.insert_one(canonical_doc)
            migrated_count += 1

    print(f"[Migration] Successfully migrated {migrated_count} complaint documents into canonical 'issues' collection.")

if __name__ == "__main__":
    migrate()
