"""
SmartCivic+ — Issue Data Model Schema and Helpers
"""
from marshmallow import Schema, fields, validate
from datetime import datetime
from bson import ObjectId

CATEGORIES = ["road", "water", "electricity", "sanitation", "drainage", "other"]
SEVERITIES = ["low", "medium", "high", "critical"]
STATUSES = [
    "submitted", "ai_reviewed", "officer_reviewed", "assigned",
    "work_started", "work_completed", "officer_verified",
    "citizen_verification", "closed", "reopened"
]
DEPARTMENTS = ["roads", "water_supply", "electrical", "sanitation", "drainage"]
SLA_STATUSES = ["on_track", "warning", "urgent", "breached"]

def create_issue_doc(citizen_id, title, description, category, issue_type, lat, lng, address, ward, images=None) -> dict:
    now = datetime.utcnow()
    return {
        "title": title.strip(),
        "description": description.strip(),
        "category": category, # road, water, electricity, sanitation, drainage, other
        "type": issue_type.strip(),
        "severity": "medium", # default, computed by AI
        "priority_score": 0.0, # computed by priority_service
        "status": "submitted",
        "location": {
            "type": "Point",
            "coordinates": [float(lng), float(lat)]
        },
        "address": address.strip(),
        "ward": ward.strip(),
        "department": "roads", # default, resolved by AI
        "citizen_id": ObjectId(citizen_id),
        "officer_id": None,
        "worker_id": None,
        "cluster_id": None,
        "duplicate_of": None,
        "duplicate_children": [],
        "ai_analysis": {
            "category": category,
            "type": issue_type.strip(),
            "severity": "medium",
            "department": "roads",
            "confidence": 0.0,
            "provider": "rule_based",
            "image_detections": [],
            "duplicate_candidates": [],
            "analyzed_at": now,
            "officer_overridden": False,
            "override_reason": None
        },
        "images": images or [], # list of image dicts: filename, url, type, uploaded_by, uploaded_at
        "sla_deadline": now, # computed by sla_service
        "sla_status": "on_track",
        "resolution_notes": "",
        "ai_verification": {
            "confidence": 0.0,
            "status": "uncertain", # verified, likely_verified, uncertain, not_verified
            "timestamp": None
        },
        "citizen_verified": None,
        "citizen_feedback": "",
        "audit_trail": [], # list of AuditLog ObjectIds
        "is_emergency": False,
        "emergency_category": None,
        "emergency_declared_at": None,
        "emergency_declared_by": None,
        "community_confirmations": [],
        "confirmation_count": 0,
        "citizen_rating": None,
        "citizen_feedback_text": None,
        "feedback_submitted_at": None,
        "original_language": "english",
        "original_description": None,
        "translated_description": None,
        "is_recurring": False,
        "recurrence_count": 0,
        "first_occurrence_at": None,
        "created_at": now,
        "updated_at": now
    }

class IssueCreateSchema(Schema):
    title = fields.Str(required=True, validate=validate.Length(min=5, max=100))
    description = fields.Str(required=True, validate=validate.Length(min=10, max=1000))
    category = fields.Str(required=True, validate=validate.OneOf(CATEGORIES))
    type = fields.Str(required=True, validate=validate.Length(min=2, max=50))
    lat = fields.Float(required=True)
    lng = fields.Float(required=True)
    address = fields.Str(required=True, validate=validate.Length(min=5, max=250))
    ward = fields.Str(required=True, validate=validate.Length(min=2, max=100))
