# db.notifications schema representation:
# {
#   _id: ObjectId,
#   user_id: ObjectId,
#   message: str,
#   type: str,
#   issue_id: ObjectId|None,
#   is_read: bool(False),
#   created_at: datetime
# }

def create_notification_doc(user_id, message, notif_type, issue_id=None):
    from datetime import datetime
    from bson import ObjectId
    return {
        "user_id": ObjectId(user_id),
        "message": message,
        "type": notif_type,
        "issue_id": ObjectId(issue_id) if issue_id else None,
        "is_read": False,
        "created_at": datetime.utcnow()
    }
