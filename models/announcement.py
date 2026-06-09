# db.announcements schema representation:
# {
#   _id: ObjectId,
#   title: str,
#   body: str,
#   community_id: ObjectId,
#   created_by: ObjectId,
#   created_at: datetime,
#   expires_at: datetime|None,
#   is_active: bool(True)
# }

def create_announcement_doc(title, body, community_id, created_by, expires_at=None):
    from datetime import datetime
    from bson import ObjectId
    return {
        "title": title,
        "body": body,
        "community_id": ObjectId(community_id),
        "created_by": ObjectId(created_by),
        "created_at": datetime.utcnow(),
        "expires_at": expires_at,
        "is_active": True
    }
