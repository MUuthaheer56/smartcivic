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
PRIORITIES = ["P0", "P1", "P2", "P3"]
DEPARTMENTS = ["roads", "water_supply", "electrical", "sanitation", "drainage", "other"]
SLA_STATUSES = ["on_track", "warning", "urgent", "breached"]

PRIORITY_TO_LABEL = {
    "P0": "critical",
    "P1": "high",
    "P2": "medium",
    "P3": "low"
}

LABEL_TO_PRIORITY = {
    "critical": "P0",
    "p0": "P0",
    "high": "P1",
    "p1": "P1",
    "medium": "P2",
    "p2": "P2",
    "low": "P3",
    "p3": "P3"
}

def normalize_priority(val: str) -> str:
    """Always returns canonical P0, P1, P2, or P3."""
    if not val:
        return "P3"
    clean = str(val).strip().lower()
    return LABEL_TO_PRIORITY.get(clean, "P3" if clean not in ["p0", "p1", "p2", "p3"] else clean.upper())

def priority_to_label(priority: str) -> str:
    """Returns critical/high/medium/low display label for canonical P0-P3."""
    norm = normalize_priority(priority)
    return PRIORITY_TO_LABEL.get(norm, "medium")

from constants.states import (
    STATUSES,
    ISSUE_STATES,
    STATUS_ALIASES,
    LEGAL_TRANSITIONS,
    validate_state_transition,
    normalize_status
)

def create_issue_doc(citizen_id, title, description, category, issue_type, lat, lng, address, ward, images=None) -> dict:
    now = datetime.utcnow()
    ward_str = str(ward).strip() if ward is not None else "Ward 1"
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
