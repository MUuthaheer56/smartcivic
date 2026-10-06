"""
SmartCivic+ — Issue Data Model Schema and Helpers
"""
from marshmallow import Schema, fields, validate
from datetime import datetime
from bson import ObjectId

CATEGORIES = [
    "road", "water", "electricity", "sanitation",
    "drainage", "noise", "other"
]
SEVERITIES = ["low", "medium", "high", "critical"]
STATUSES = [
    "submitted", "ai_reviewed", "officer_reviewed", "assigned",
    "work_started", "work_completed", "officer_verified",
    "citizen_verification", "closed", "reopened"
]
DEPARTMENTS = ["roads", "water_supply", "electrical", "sanitation", "drainage", "other"]
SLA_STATUSES = ["on_track", "warning", "urgent", "breached"]

ISSUE_STATES = [
    "SUBMITTED",
    "AI_ANALYZED",
    "OFFICER_REVIEW",
    "ASSIGNED",
    "EN_ROUTE",
    "IN_PROGRESS",
    "WORK_COMPLETED",
    "OFFICER_VERIFICATION",
    "RESOLVED",
    "RESIDENT_CONFIRMATION",
    "CLOSED",
    "REOPENED"
]

def validate_state_transition(current_state: str, target_state: str) -> bool:
    """Strict transition verification for the issue lifecycle."""
    curr = str(current_state or "").upper().strip()
    target = str(target_state or "").upper().strip()
    
    alias_map = {
        "AI_REVIEWED": "AI_ANALYZED",
        "UNDER_REVIEW": "OFFICER_REVIEW",
        "OFFICER_REVIEWED": "OFFICER_REVIEW",
        "WORK_STARTED": "IN_PROGRESS",
        "OFFICER_VERIFIED": "OFFICER_VERIFICATION",
        "CITIZEN_VERIFICATION": "RESIDENT_CONFIRMATION"
    }
    curr = alias_map.get(curr, curr)
    target = alias_map.get(target, target)

    transitions = {
        "SUBMITTED": ["AI_ANALYZED", "OFFICER_REVIEW"],
        "AI_ANALYZED": ["OFFICER_REVIEW"],
        "OFFICER_REVIEW": ["ASSIGNED", "REOPENED"],
        "ASSIGNED": ["EN_ROUTE", "IN_PROGRESS"],
        "EN_ROUTE": ["IN_PROGRESS"],
        "IN_PROGRESS": ["WORK_COMPLETED"],
        "WORK_COMPLETED": ["OFFICER_VERIFICATION"],
        "OFFICER_VERIFICATION": ["RESOLVED", "REOPENED"],
        "RESOLVED": ["RESIDENT_CONFIRMATION", "REOPENED"],
        "RESIDENT_CONFIRMATION": ["CLOSED", "REOPENED"],
        "REOPENED": ["OFFICER_REVIEW"]
    }
    return target in transitions.get(curr, [])

def create_issue_doc(citizen_id, title, description, category, issue_type, lat, lng, address, ward, images=None) -> dict:
    now = datetime.utcnow()
    ward_str = ward.strip() if ward else "Ward 1"
    return {
        "title": title.strip() if title else description.strip()[:50],
        "description": description.strip(),
        "category": category, # road, water, electricity, sanitation, drainage, other
        "type": issue_type.strip(),
        "service": category,
        "issue_type": issue_type.strip(),
        "severity": "medium", # default, computed by AI
        "priority": "P3",
        "priority_score": 0.0, # computed by priority_service
        "status": "submitted",
        "emergency": False,
        "emergency_state": None,
        "location": {
            "type": "Point",
            "coordinates": [float(lng), float(lat)]
        },
        "address": (address or "MG Road, Bengaluru").strip(),
        "ward": ward_str,
        "ward_id": ward_str.lower().replace(" ", "_"),
        "department": "roads", # default, resolved by AI
        "citizen_id": ObjectId(citizen_id) if citizen_id else None,
        "reporter_id": str(citizen_id) if citizen_id else None,
        "reporter_verified": False,
        "officer_id": None,
        "assigned_officer_id": None,
        "worker_id": None,
        "cluster_id": None,
        "duplicate_of": None,
        "duplicate_children": [],
        "ai_confidence": 0.0,
        "ai_route_decision": None,
        "cips_score":            None,
        "evidence_reliability":  None,
        "evidence_agreement":    None,
        "ctve_triggered":        False,
        "ctve_message":          None,
        "verification_required": False,
        "monsoon_active":        False,
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
        "impact": {
            "road_damage_risk": None,
            "safety_risk": None,
            "traffic_impact": None,
            "resident_impact": None,
            "worsening_risk": None,
            "impact_summary": None
        },
        "supporters": [],
        "support_count": 0,
        "verification_status": "PENDING",
        "confidence_score": 0.0,
        "authority_primary": None,
        "authority_secondary": [],
        "authority_reference_id": None,
        "forwarded_at": None,
        "food_details": None,
        "is_multi_issue": False,
        "sub_issues": [],
        "parent_id": None,
        "images": images or [], # list of image dicts: filename, url, type, uploaded_by, uploaded_at
        "photos": [img.get("url") if isinstance(img, dict) else img for img in (images or [])],
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
        "status_history": [
            {
                "status": "SUBMITTED",
                "timestamp": now,
                "actor": "citizen",
                "note": ""
            }
        ],
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
