# db.issues schema representation:
# {
#   _id: ObjectId,
#   title: str,
#   description: str,
#   category: str("pothole"|"garbage"|"streetlight"|"water"|"sewage"|"noise"|"other"),
#   images: [str],
#   lat: float,
#   lng: float,
#   address: str,
#   community_id: ObjectId,
#   reporter_id: ObjectId,
#   is_anonymous: bool(False),
#   status: str("pending_validation"|"validated"|"assigned"|"in_progress"|"resolved"|"rejected"),
#   severity: int(1-5, set on validation),
#   severity_override: int|None,
#   severity_override_by: ObjectId|None,
#   confirm_votes: int(0),
#   deny_votes: int(0),
#   severity_votes: [int],
#   upvotes: int(0),
#   upvoted_by: [ObjectId],
#   linked_issue_ids: [ObjectId],
#   validated_at: datetime|None,
#   assigned_to: ObjectId|None,
#   assigned_at: datetime|None,
#   resolved_at: datetime|None,
#   resolution_note: str|None,
#   resolution_image: str|None,
#   created_at: datetime,
#   sla_deadline: datetime|None,
#   sla_breached: bool(False),
#   comments: [{user_id:ObjectId, name:str, text:str, timestamp:datetime}],
#   status_history: [{status:str, changed_by:ObjectId|None, timestamp:datetime, note:str}]
# }

def create_issue_doc(title, description, category, lat, lng, address, community_id, reporter_id, is_anonymous=False, images=None):
    from datetime import datetime
    from bson import ObjectId
    return {
        "title": title,
        "description": description,
        "category": category,
        "images": images or [],
        "lat": float(lat),
        "lng": float(lng),
        "address": address,
        "community_id": ObjectId(community_id),
        "reporter_id": ObjectId(reporter_id),
        "is_anonymous": is_anonymous,
        "status": "pending_validation",
        "severity": 3,
        "severity_override": None,
        "severity_override_by": None,
        "confirm_votes": 0,
        "deny_votes": 0,
        "severity_votes": [],
        "upvotes": 0,
        "upvoted_by": [],
        "linked_issue_ids": [],
        "validated_at": None,
        "assigned_to": None,
        "assigned_at": None,
        "resolved_at": None,
        "resolution_note": None,
        "resolution_image": None,
        "created_at": datetime.utcnow(),
        "sla_deadline": None,
        "sla_breached": False,
        "comments": [],
        "status_history": [
            {
                "status": "pending_validation",
                "changed_by": ObjectId(reporter_id),
                "timestamp": datetime.utcnow(),
                "note": "Issue reported."
            }
        ]
    }
