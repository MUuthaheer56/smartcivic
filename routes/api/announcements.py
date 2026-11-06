"""
routes/api/announcements.py
SmartCivic Announcement Broadcast API (Admin, Citizen, Worker)
Supports:
- POST /api/admin/announcements: broadcast announcement with plain-text sanitization, audit trail, Socket.IO broadcast
- GET /api/announcements/active: fetch active, unexpired announcements matching audience + user read state
- POST /api/announcements/<id>/read: mark announcement as read by authenticated user
- POST /api/admin/announcements/<id>/retract: retract announcement and broadcast retraction event
- GET /api/admin/announcements: admin history with read counts
"""

import html
import re
from datetime import datetime, timedelta
from bson import ObjectId
from flask import Blueprint, request, jsonify, g, current_app

from app import db, limiter, socketio
from routes.auth import require_auth, require_role
from utils.auth_helpers import verified_required
from services.audit_service import log_audit
from utils import serialize

announcements_api_bp = Blueprint('announcements_api', __name__)


def sanitize_plain_text(val: str, max_length: int = 1000) -> str:
    """Strips all HTML tags and unescapes HTML entities to ensure strictly plain text."""
    if not isinstance(val, str):
        return ""
    # Strip HTML tags
    clean = re.sub(r"<[^>]*?>", "", val)
    # Unescape HTML entities
    clean = html.unescape(clean).strip()
    return clean[:max_length]


@announcements_api_bp.route('/api/admin/announcements', methods=['POST'])
@require_auth
@require_role('admin')
@verified_required
@limiter.limit("10 per hour")
def broadcast_announcement():
    payload = request.get_json(silent=True) or request.form.to_dict() or {}

    raw_title = payload.get("title", "")
    raw_body = payload.get("body", "")

    title = sanitize_plain_text(raw_title, max_length=120)
    body = sanitize_plain_text(raw_body, max_length=1000)

    if not title or len(title) < 3:
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": "Title must be at least 3 characters."}}), 400

    if not body or len(body) < 5:
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": "Body must be at least 5 characters."}}), 400

    severity = str(payload.get("severity", "info")).lower()
    if severity not in ["info", "warning", "critical"]:
        severity = "info"

    audience = str(payload.get("audience", "both")).lower()
    if audience not in ["citizen", "worker", "both"]:
        audience = "both"

    pinned = bool(payload.get("pinned", False))

    # Idempotency key handling
    idempotency_key = payload.get("idempotency_key")
    if idempotency_key:
        idempotency_key = str(idempotency_key).strip()
        existing = db.announcements.find_one({"idempotency_key": idempotency_key})
        if existing:
            return jsonify({
                "success": True,
                "message": "Announcement already processed (idempotent)",
                "announcement": serialize(existing)
            }), 200

    # Expiry calculation (default 24 hours, min 1 hour, max 30 days)
    expires_in_hours = 24
    try:
        if "expires_in_hours" in payload:
            expires_in_hours = max(1, min(720, int(payload["expires_in_hours"])))
    except (ValueError, TypeError):
        expires_in_hours = 24

    now = datetime.utcnow()
    expires_at = now + timedelta(hours=expires_in_hours)

    admin_id = ObjectId(g.current_user["_id"])
    announcement_doc = {
        "_id": ObjectId(),
        "title": title,
        "body": body,
        "severity": severity,
        "audience": audience,
        "pinned": pinned,
        "status": "active",
        "created_by": admin_id,
        "created_by_name": g.current_user.get("name", "Administrator"),
        "created_at": now,
        "expires_at": expires_at,
        "idempotency_key": idempotency_key or None
    }

    db.announcements.insert_one(announcement_doc)

    # Audit log
    log_audit(
        entity_type="announcement",
        entity_id=announcement_doc["_id"],
        actor_id=admin_id,
        action="ADMIN_ANNOUNCEMENT_BROADCAST",
        reason=f"Broadcast {severity} announcement to {audience}: {title}"
    )

    serialized = serialize(announcement_doc)

    # Realtime Socket.IO Broadcast to /civic namespace
    try:
        broadcast_payload = {
            "announcement": serialized,
            "timestamp": now.isoformat()
        }
        if audience in ("citizen", "both"):
            socketio.emit("announcement_broadcast", broadcast_payload, room="role_citizen", namespace="/civic")
            socketio.emit("announcement_broadcast", broadcast_payload, room="role_resident", namespace="/civic")
        if audience in ("worker", "both"):
            socketio.emit("announcement_broadcast", broadcast_payload, room="role_worker", namespace="/civic")
    except Exception as emit_err:
        current_app.logger.warning(f"Socket.IO announcement broadcast warning: {emit_err}")

    return jsonify({
        "success": True,
        "message": "Announcement broadcast successfully.",
        "announcement": serialized
    }), 201


@announcements_api_bp.route('/api/announcements/active', methods=['GET'])
@require_auth
def get_active_announcements():
    user = g.current_user
    user_role = str(user.get("role", "")).lower()

    now = datetime.utcnow()
    query = {
        "status": "active",
        "expires_at": {"$gt": now}
    }

    if user_role in ("citizen", "resident"):
        query["audience"] = {"$in": ["citizen", "both"]}
    elif user_role == "worker":
        query["audience"] = {"$in": ["worker", "both"]}
    # Admins and officers see all active announcements

    raw_list = list(db.announcements.find(query).sort([("pinned", -1), ("created_at", -1)]).limit(50))

    # Read tracking for current user
    user_id = ObjectId(user["_id"])
    read_docs = list(db.announcement_reads.find({"user_id": user_id}, {"announcement_id": 1}))
    read_ids = {str(d["announcement_id"]) for d in read_docs if "announcement_id" in d}

    serialized = serialize(raw_list)
    for item in serialized:
        item["is_read"] = str(item.get("_id")) in read_ids

    return jsonify({"success": True, "data": serialized}), 200


@announcements_api_bp.route('/api/announcements/<announcement_id>/read', methods=['POST'])
@require_auth
def mark_announcement_read(announcement_id):
    if not ObjectId.is_valid(announcement_id):
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": "Invalid announcement ID."}}), 400

    ann_oid = ObjectId(announcement_id)
    user_id = ObjectId(g.current_user["_id"])

    db.announcement_reads.update_one(
        {"announcement_id": ann_oid, "user_id": user_id},
        {"$setOnInsert": {"read_at": datetime.utcnow()}},
        upsert=True
    )

    return jsonify({"success": True, "message": "Marked as read."}), 200


@announcements_api_bp.route('/api/admin/announcements/<announcement_id>/retract', methods=['POST'])
@require_auth
@require_role('admin')
def retract_announcement(announcement_id):
    if not ObjectId.is_valid(announcement_id):
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": "Invalid announcement ID."}}), 400

    ann_oid = ObjectId(announcement_id)
    now = datetime.utcnow()
    admin_id = ObjectId(g.current_user["_id"])

    res = db.announcements.update_one(
        {"_id": ann_oid, "status": "active"},
        {"$set": {
            "status": "retracted",
            "retracted_at": now,
            "retracted_by": admin_id
        }}
    )

    if res.matched_count == 0:
        return jsonify({"success": False, "error": {"code": "NOT_FOUND", "message": "Active announcement not found."}}), 404

    log_audit(
        entity_type="announcement",
        entity_id=ann_oid,
        actor_id=admin_id,
        action="ADMIN_ANNOUNCEMENT_RETRACTED",
        reason=f"Retracted announcement {announcement_id}"
    )

    try:
        socketio.emit(
            "announcement_retracted",
            {"announcement_id": str(announcement_id)},
            namespace="/civic"
        )
    except Exception as emit_err:
        current_app.logger.warning(f"Socket.IO announcement retract warning: {emit_err}")

    return jsonify({"success": True, "message": "Announcement retracted successfully."}), 200


@announcements_api_bp.route('/api/admin/announcements', methods=['GET'])
@require_auth
@require_role('admin')
def list_admin_announcements():
    raw_list = list(db.announcements.find().sort("created_at", -1).limit(100))
    serialized = serialize(raw_list)

    for item in serialized:
        ann_oid = ObjectId(item["_id"]) if ObjectId.is_valid(item.get("_id")) else None
        if ann_oid:
            item["read_count"] = db.announcement_reads.count_documents({"announcement_id": ann_oid})
        else:
            item["read_count"] = 0

    return jsonify({"success": True, "data": serialized}), 200
