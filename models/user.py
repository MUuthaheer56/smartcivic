"""
SmartCivic+ — User Data Model Schema and Helpers
"""
from marshmallow import Schema, fields, validate
from datetime import datetime

# Citizen reputation tiers
CIVIC_TIERS = {
    "ward_guardian": 150,
    "verifier": 50,
    "reporter": 0
}

def derive_citizen_tier(score: int) -> str:
    if score >= CIVIC_TIERS["ward_guardian"]:
        return "ward_guardian"
    if score >= CIVIC_TIERS["verifier"]:
        return "verifier"
    return "reporter"

def create_user_doc(name: str, email: str, password_hash: str, role: str, ward: str = "Ward 1", skills: list = None) -> dict:
    now = datetime.utcnow()
    normalized_role = "resident" if role in ["resident", "citizen"] else role
    doc = {
        "name": name.strip(),
        "email": email.lower().strip(),
        "password_hash": password_hash,
        "role": normalized_role, # resident, officer, worker
        "ward": (ward or "Ward 1").strip(),
        "created_at": now,
        "last_login": None
    }
    
    if normalized_role in ["resident", "citizen"]:
        doc.update({
            "civic_score": 0,
            "role_tier": "reporter",
            "reports_submitted": 0,
            "reports_verified_accurate": 0
        })
    elif normalized_role == "worker":
        doc.update({
            "skills": skills or [],
            "current_location": {
                "type": "Point",
                "coordinates": [77.5946, 12.9716] # default Bangalore
            },
            "active_assignments": 0,
            "is_available": True,
            "status": "available",
            "average_rating": 0.0,
            "total_ratings": 0
        })
        
    return doc

class UserRegisterSchema(Schema):
    name = fields.Str(required=True, validate=validate.Length(min=2, max=100))
    email = fields.Email(required=True)
    password = fields.Str(required=True, validate=validate.Length(min=6, max=100))
    role = fields.Str(required=True, validate=validate.OneOf(["citizen", "resident", "officer", "worker"]))
    ward = fields.Str(required=False, validate=validate.Length(min=1, max=100))
    skills = fields.List(fields.Str(), required=False)
    invite_code = fields.Str(required=False)

class UserLoginSchema(Schema):
    email = fields.Email(required=True)
    password = fields.Str(required=True)
