"""
SmartCivic+ — User Data Model Schema and Helpers
"""
from marshmallow import Schema, fields, validate, EXCLUDE, pre_load
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
    pending_role = normalized_role in ["resident", "citizen", "worker"]
    doc = {
        "name": name.strip(),
        "email": email.lower().strip(),
        "password_hash": password_hash,
        "role": normalized_role, # resident, officer, worker
        "status": "pending_verification" if pending_role else "active",
        "verified": False if pending_role else True,
        "ward": (ward or "Ward 1").strip(),
        "ward_id": None if pending_role else (ward or "Ward 1").strip().lower().replace(" ", "_"),
        "street_id": None,
        "area_code": None,
        "verification_status": "pending" if pending_role else "approved",
        "verification_doc": None,
        "verification_method": None,
        "verified_at": None,
        "created_at": now,
        "updated_at": now,
        "last_login": None
    }

    
    if normalized_role in ["resident", "citizen"]:
        doc.update({
            "civic_score": 0,
            "role_tier": "reporter",
            "tier": "reporter",
            "reports_submitted": 0,
            "reports_verified_accurate": 0
        })
    elif normalized_role == "officer":
        doc.update({
            "department": "GBA-CORP-ROADS",
            "skills": skills or ["road_damage", "pothole"],
            "ward_coverage": [(ward or "Ward 1").strip().lower().replace(" ", "_")],
            "max_workload": 8,
            "current_workload": 0,
            "officer_available": True
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
            "status": "pending_verification" if pending_role else "available",
            "average_rating": 0.0,
            "total_ratings": 0
        })
        
    return doc

class UserRegisterSchema(Schema):
    class Meta:
        unknown = EXCLUDE

    name = fields.Str(required=True, validate=validate.Length(min=2, max=100))
    email = fields.Email(required=True)
    password = fields.Str(required=True, validate=validate.Length(min=6, max=100))
    role = fields.Str(required=False, dump_default="citizen", load_default="citizen", validate=validate.OneOf(["citizen", "resident", "officer", "worker"]))
    ward = fields.Str(required=False, validate=validate.Length(min=1, max=100))
    skills = fields.List(fields.Str(), required=False)
    invite_code = fields.Str(required=False)

    @pre_load
    def process_input(self, data, **kwargs):
        if not isinstance(data, dict):
            return data
        mutable_data = dict(data)
        if "role" not in mutable_data or not mutable_data["role"]:
            mutable_data["role"] = "citizen"
        if "skills" in mutable_data:
            s_val = mutable_data["skills"]
            if isinstance(s_val, str):
                mutable_data["skills"] = [s.strip() for s in s_val.split(",") if s.strip()]
        return mutable_data

class UserLoginSchema(Schema):
    email = fields.Email(required=True)
    password = fields.Str(required=True)

def get_db():
    from app import db
    return db
