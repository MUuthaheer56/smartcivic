"""
SmartCivic+ — Cluster Data Model
Clusters nearby similar complaints.
"""
from datetime import datetime
from bson import ObjectId

def create_cluster_doc(issue_id, lat, lng, category, issue_type, severity, ward) -> dict:
    now = datetime.utcnow()
    return {
        "issue_ids": [ObjectId(issue_id)],
        "location": {
            "type": "Point",
            "coordinates": [float(lng), float(lat)]
        },
        "category": category,
        "type": issue_type,
        "severity": severity,
        "report_count": 1,
        "ward": ward,
        "status": "open",
        "created_at": now,
        "updated_at": now
    }
