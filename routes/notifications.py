from flask import Blueprint, jsonify, g
from bson import ObjectId
from app import db
from services.auth_service import require_auth, require_role

notifications_bp = Blueprint('notifications', __name__)

@notifications_bp.route('/', methods=['GET'])
@require_auth
def list_notifications():
    user_id = ObjectId(g.user['user_id'])
    try:
        notifs = list(db.notifications.find({"user_id": user_id}).sort("created_at", -1))
        # Format results for serialization
        for n in notifs:
            n['_id'] = str(n['_id'])
            n['user_id'] = str(n['user_id'])
            if n.get('issue_id'):
                n['issue_id'] = str(n['issue_id'])
            n['created_at'] = n['created_at'].isoformat()
        return jsonify({"success": True, "data": notifs})
    except Exception as e:
        return jsonify({"success": False, "message": f"Server error: {str(e)}"}), 500

@notifications_bp.route('/read/<notif_id>', methods=['PUT'])
@require_auth
def mark_read(notif_id):
    try:
        db.notifications.update_one(
            {"_id": ObjectId(notif_id), "user_id": ObjectId(g.user['user_id'])},
            {"$set": {"is_read": True}}
        )
        return jsonify({"success": True, "message": "Notification marked as read"})
    except Exception as e:
        return jsonify({"success": False, "message": f"Server error: {str(e)}"}), 500

@notifications_bp.route('/read-all', methods=['PUT'])
@require_auth
def mark_all_read():
    try:
        db.notifications.update_many(
            {"user_id": ObjectId(g.user['user_id']), "is_read": False},
            {"$set": {"is_read": True}}
        )
        return jsonify({"success": True, "message": "All notifications marked as read"})
    except Exception as e:
        return jsonify({"success": False, "message": f"Server error: {str(e)}"}), 500

@notifications_bp.route('/trigger-digest/<community_id>', methods=['POST'])
@require_role('authority')
def trigger_digest(community_id):
    from services.notification_service import send_weekly_digest
    try:
        send_weekly_digest(community_id)
        return jsonify({"success": True, "message": "Weekly digest emails sent successfully."})
    except Exception as e:
        return jsonify({"success": False, "message": f"Error triggering digest: {str(e)}"}), 500
