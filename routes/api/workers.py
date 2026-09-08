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


@workers_api_bp.route('/api/workers/<worker_id>/tasks', methods=['GET'])
@require_auth
@require_role('worker', 'officer')
def get_worker_tasks(worker_id):
    if g.current_user["role"] == "worker" and str(g.current_user["_id"]) != str(worker_id):
        return jsonify({"success": False, "error": {"code": "FORBIDDEN", "message": "Worker can only view own tasks."}}), 403
        
    try:
        w_obj = ObjectId(worker_id) if ObjectId.is_valid(worker_id) else None
        worker_doc = db.users.find_one({"_id": w_obj}) if w_obj else db.users.find_one({"_id": worker_id})
        worker_prof = db.workers.find_one({"_id": w_obj}) if w_obj else db.workers.find_one({"user_id": worker_id})
        
        w_coords = None
        if worker_prof and worker_prof.get("location", {}).get("latitude"):
            w_coords = [worker_prof["location"].get("longitude", 77.5946), worker_prof["location"].get("latitude", 12.9716)]
        elif worker_doc:
            w_coords = worker_doc.get("current_location", {}).get("coordinates")
        if not w_coords:
            w_coords = [77.5946, 12.9716]
            
        w_lat, w_lng = w_coords[1], w_coords[0]
        
        query = {
            "$or": [
                {"worker_id": w_obj},
                {"worker_id": str(worker_id)},
                {"assignment.worker_id": str(worker_id)}
            ]
        }
        
        issues = list(db.issues.find(query).sort("created_at", -1))
        tasks = []
        from services.route_service import haversine
        for iss in issues:
            coords = iss.get("location", {}).get("coordinates", [77.5946, 12.9716])
            i_lat = iss.get("location", {}).get("latitude", coords[1])
            i_lng = iss.get("location", {}).get("longitude", coords[0])
            
            dist_m = int(haversine((w_lat, w_lng), (i_lat, i_lng)) * 1000)
            
            imgs = iss.get("images") or []
            first_url = iss.get("image", {}).get("url") or (imgs[0].get("url") if imgs else "/static/uploads/issues/placeholder.jpg")
            
            sla_dl = iss.get("sla", {}).get("deadline") or (iss.get("sla_deadline").isoformat() if hasattr(iss.get("sla_deadline"), "isoformat") else str(iss.get("sla_deadline")))

            tasks.append({
                "issue_id": iss.get("issue_id") or str(iss["_id"]),
                "_id": str(iss["_id"]),
                "description": iss.get("description"),
                "priority": iss.get("priority") or iss.get("severity", "medium"),
                "image_url": first_url,
                "location": {
                    "latitude": i_lat,
                    "longitude": i_lng,
                    "address": iss.get("address") or iss.get("location", {}).get("address", "")
                },
                "distance_meters": dist_m,
                "status": iss.get("status"),
                "sla_deadline": sla_dl
            })
            
        return jsonify({"success": True, "data": tasks}), 200
    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"success": False, "error": {"code": "SERVER_ERROR", "message": "An internal server error occurred."}}), 500

