# db.users schema representation:
# {
#   _id: ObjectId,
#   name: str,
#   email: str(unique),
#   password_hash: str,
#   role: str("resident"|"authority"|"field_worker"),
#   community_id: ObjectId,
#   is_verified: bool(default False),
#   verification_doc: str|None,
#   created_at: datetime,
#   last_login: datetime,
#   reports_count: int(0),
#   votes_count: int(0),
#   issues_resolved_count: int(0),
#   reputation_score: int(0),
#   reputation_tier: str("Newcomer"|"Active Resident"|"Civic Champion"|"Community Hero"),
#   is_anonymous_by_default: bool(False),
#   last_lat: float|None,
#   last_lng: float|None,
#   onboarding_complete: bool(False),
#   preferred_language: str("en"|"hi"|"kn", default "en")
# }

def create_user_doc(name, email, password_hash, role, community_id, verification_doc=None, is_verified=False):
    from datetime import datetime
    from bson import ObjectId
    return {
        "name": name,
        "email": email,
        "password_hash": password_hash,
        "role": role,
        "community_id": ObjectId(community_id) if community_id else None,
        "is_verified": is_verified,
        "verification_doc": verification_doc,
        "created_at": datetime.utcnow(),
        "last_login": datetime.utcnow(),
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
