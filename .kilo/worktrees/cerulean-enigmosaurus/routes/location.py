"""
SmartCivic — Location & Spatial Intelligence Blueprint
"""
from flask import Blueprint, request, jsonify, g
from datetime import datetime, timedelta
from app import db
from routes.auth import require_auth
from utils.geo_utils import haversine

location_bp = Blueprint('location_bp', __name__)

@location_bp.route("/api/location/context", methods=["GET"])
@location_bp.route("/location/context", methods=["GET"])
@require_auth
def get_location_context():
    """
    Given lat/lng, return:
      - ward_id (for routing)
      - ward_name
      - location_type (hospital/school/main_road/residential...)
      - nearby_complaints_count (last 90 days, same ward)
    Used by the complaint submission form and CEFAP pipeline.
    """
    try:
        lat = float(request.args.get("lat", 0))
        lng = float(request.args.get("lng", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid coordinates", "message": "Invalid coordinates"}), 400

    ward = _find_ward_by_coords(lat, lng)

    since = datetime.utcnow() - timedelta(days=90)
    ward_id = ward.get("ward_id") if ward else None
    
    nearby_count = db.issues.count_documents({
        "ward_id": ward_id,
        "created_at": {"$gte": since},
    }) if ward_id else 0

    return jsonify({
        "success": True,
        "ward_id": ward_id,
        "ward_name": ward.get("ward_name") if ward else None,
        "location_type": _infer_location_type(lat, lng),
        "nearby_complaints_count": nearby_count,
        "data": {
            "ward_id": ward_id,
            "ward_name": ward.get("ward_name") if ward else None,
            "location_type": _infer_location_type(lat, lng),
            "nearby_complaints_count": nearby_count
        }
    }), 200

def _find_ward_by_coords(lat, lng):
    """Nearest-ward lookup using Haversine."""
    try:
        wards = list(db.ward_registry.find({"active": True},
                     {"ward_id": 1, "ward_name": 1, "center_lat": 1, "center_lng": 1}))
        if not wards:
            wards = list(db.ward_registry.find({}, {"ward_id": 1, "ward_name": 1, "center_lat": 1, "center_lng": 1}))
        if not wards:
            return {"ward_id": "ward_1", "ward_name": "Ward 1"}
            
        best = min(
            wards,
            key=lambda w: haversine(
                (lat, lng),
                (w.get("center_lat", lat), w.get("center_lng", lng))
            ),
            default=None
        )
        return best or {"ward_id": "ward_1", "ward_name": "Ward 1"}
    except Exception:
        return {"ward_id": "ward_1", "ward_name": "Ward 1"}

def _infer_location_type(lat, lng):
    """
    Returns location criticality type for CEFAP location impact signal.
    """
    return "unknown"
