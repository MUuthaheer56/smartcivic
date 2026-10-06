"""
SmartCivic+ — Notifications API Blueprint
Serves persisted notification history and read-state updates per user.
"""
from flask import Blueprint, jsonify, g, request
from bson import ObjectId
from app import db, limiter
from routes.auth import require_auth
from utils import serialize, parse_object_id

notifications_api_bp = Blueprint('notifications_api', __name__)


@notifications_api_bp.route('/api/notifications', methods=['GET'])
@require_auth
@limiter.limit("60 per minute")
def list_notifications():
    """Return the current user's notifications, newest first."""
    limit = min(int(request.args.get("limit", 30)), 100)
    only_unread = request.args.get("unread", "false").lower() == "true"

    query = {"user_id": g.current_user["_id"]}
    if only_unread:
        query["is_read"] = False

    notifs = list(
        db.notifications.find(query)
        .sort("created_at", -1)
        .limit(limit)
    )
    unread_count = db.notifications.count_documents(
        {"user_id": g.current_user["_id"], "is_read": False}
    )
    return jsonify({
        "success": True,
        "data": serialize(notifs),
        "unread_count": unread_count
    }), 200


@notifications_api_bp.route('/api/notifications/<id>/read', methods=['POST'])
@require_auth
def mark_notification_read(id):
    """Mark a single notification as read."""
    parsed_id = parse_object_id(id)
    if not parsed_id:
        return jsonify({"success": False, "error": {"code": "NOT_FOUND", "message": "Invalid notification ID."}}), 404

    result = db.notifications.update_one(
        {"_id": parsed_id, "user_id": g.current_user["_id"]},
        {"$set": {"is_read": True}}
    )
    if result.matched_count == 0:
        return jsonify({"success": False, "error": {"code": "NOT_FOUND", "message": "Notification not found."}}), 404

    return jsonify({"success": True, "message": "Notification marked as read."}), 200


@notifications_api_bp.route('/api/notifications/mark-read', methods=['POST'])
@notifications_api_bp.route('/api/notifications/read-all', methods=['POST'])
@require_auth
def mark_all_read():
    """Mark specific notification IDs or all of the current user's notifications as read."""
    data = request.get_json() or {}
    ids = data.get("ids", [])
    if ids:
        object_ids = [parse_object_id(i) for i in ids if parse_object_id(i)]
        db.notifications.update_many(
            {"_id": {"$in": object_ids}, "user_id": g.current_user["_id"]},
            {"$set": {"is_read": True}}
        )
    else:
        db.notifications.update_many(
            {"user_id": g.current_user["_id"], "is_read": False},
            {"$set": {"is_read": True}}
        )
    return jsonify({"success": True, "message": "Notifications marked as read."}), 200

