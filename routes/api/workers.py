"""
SmartCivic+ — Workers API Blueprint
Provides worker search, recommendation profiles, and real-time gps locations.
"""
from flask import Blueprint, request, jsonify, g, current_app
from bson import ObjectId
from app import db, limiter
from routes.auth import require_auth, require_role
from services import assignment_service
from utils import serialize, parse_object_id

workers_api_bp = Blueprint('workers_api', __name__)

@workers_api_bp.route('/api/workers/recommend', methods=['GET'])
@require_auth
@require_role('officer')
def recommend_workers():
    issue_id = request.args.get("issue_id")
    if not issue_id:
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": "issue_id query parameter required."}}), 422
        
    parsed_id = parse_object_id(issue_id)
    if not parsed_id:
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": "Invalid issue_id format."}}), 422
        
    issue = db.issues.find_one({"_id": parsed_id})
    if not issue:
        return jsonify({"success": False, "error": {"code": "NOT_FOUND", "message": "Issue not found."}}), 404
        
    try:
        recs = assignment_service.recommend_workers(issue)
        return jsonify({"success": True, "data": recs}), 200
    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"success": False, "error": {"code": "SERVER_ERROR", "message": "An internal server error occurred."}}), 500

@workers_api_bp.route('/api/workers', methods=['GET'])
@require_auth
@require_role('officer')
def list_workers():
    # Filter by ward if officer belongs to a specific ward
    query = {"role": "worker"}
    officer_ward = g.current_user.get("ward")
    if officer_ward != "all":
        query["ward"] = officer_ward
        
    workers = list(db.users.find(query, {
        "password_hash": 0,
        "created_at": 0,
        "last_login": 0
    }))
    return jsonify({"success": True, "data": serialize(workers)}), 200


@workers_api_bp.route('/api/workers/me/location', methods=['PUT'])
@require_auth
@require_role('worker')
@limiter.limit("30 per minute")
def update_my_location():
    """Allow field workers to update their current GPS coordinates."""
    data = request.get_json() or {}
    lat = data.get("lat")
    lng = data.get("lng")

    if lat is None or lng is None:
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": "lat and lng are required."}}), 422

    try:
        lat = float(lat)
        lng = float(lng)
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": "lat and lng must be numeric."}}), 422

    # Basic coordinate sanity check
    if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": "Coordinates out of valid range."}}), 422

    from datetime import datetime
    db.users.update_one(
        {"_id": g.current_user["_id"]},
        {"$set": {
            "current_location": {
                "type": "Point",
                "coordinates": [lng, lat]
            },
            "location_updated_at": datetime.utcnow()
        }}
    )
    return jsonify({"success": True, "message": "Location updated."}), 200

