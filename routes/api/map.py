"""
SmartCivic+ — Map GIS Layers API Blueprint
Provides geo-clusters, heatmaps, live worker locations, and OSRM route calculations.
"""
from flask import Blueprint, jsonify, g, request, current_app
from bson import ObjectId
from app import db
from routes.auth import require_auth, require_role
from services import route_service
from utils import serialize, parse_object_id

map_api_bp = Blueprint('map_api', __name__)

@map_api_bp.route('/api/map/issues', methods=['GET'])
@require_auth
def get_map_issues():
    # Only return coordinate and metadata to minimize payload size
    query = {"status": {"$nin": ["closed", "rejected"]}}
    
    # Ward boundaries
    officer_ward = g.current_user.get("ward")
    if g.current_user["role"] == "officer" and officer_ward != "all":
        query["ward"] = officer_ward
    elif g.current_user["role"] == "citizen":
        # A citizen can see public issue pins in the system
        pass
        
    issues = list(db.issues.find(query, {
        "title": 1,
        "category": 1,
        "type": 1,
        "severity": 1,
        "status": 1,
        "location": 1,
        "ward": 1,
        "confirmation_count": 1
    }))
    
    return jsonify({"success": True, "data": serialize(issues)}), 200

@map_api_bp.route('/api/map/clusters', methods=['GET'])
@require_auth
def get_map_clusters():
    query = {"status": "open"}
    officer_ward = g.current_user.get("ward")
    if g.current_user["role"] == "officer" and officer_ward != "all":
        query["ward"] = officer_ward
        
    clusters = list(db.clusters.find(query))
    return jsonify({"success": True, "data": serialize(clusters)}), 200

@map_api_bp.route('/api/map/heatmap', methods=['GET'])
@require_auth
def get_map_heatmap():
    query = {"status": {"$nin": ["closed", "rejected"]}}
    officer_ward = g.current_user.get("ward")
    if g.current_user["role"] == "officer" and officer_ward != "all":
        query["ward"] = officer_ward
        
    issues = list(db.issues.find(query, {"location": 1, "severity": 1}))
    
    # Format: [lat, lng, weight]
    heatmap_data = []
    weight_map = {"low": 0.2, "medium": 0.5, "high": 0.8, "critical": 1.0}
    
    for iss in issues:
        coords = iss.get("location", {}).get("coordinates", [])
        if len(coords) == 2:
            lng, lat = coords[0], coords[1]
            w = weight_map.get(iss.get("severity", "medium").lower(), 0.5)
            heatmap_data.append([lat, lng, w])
            
    return jsonify({"success": True, "data": heatmap_data}), 200

@map_api_bp.route('/api/map/workers', methods=['GET'])
@require_auth
@require_role('officer')
def get_map_workers():
    query = {"role": "worker"}
    officer_ward = g.current_user.get("ward")
    if officer_ward != "all":
        query["ward"] = officer_ward
        
    workers = list(db.users.find(query, {
        "name": 1,
        "email": 1,
        "skills": 1,
        "current_location": 1,
        "active_assignments": 1,
        "is_available": 1
    }))
    
    return jsonify({"success": True, "data": serialize(workers)}), 200

@map_api_bp.route('/api/map/route', methods=['GET'])
@require_auth
def get_optimized_route():
    worker_id = request.args.get("worker_id")
    issue_ids_raw = request.args.get("issue_ids", "")
    
    if not worker_id:
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": "worker_id required."}}), 422
        
    parsed_worker_id = parse_object_id(worker_id)
    if not parsed_worker_id:
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": "Invalid worker_id format."}}), 422
        
    worker = db.users.find_one({"_id": parsed_worker_id, "role": "worker"})
    if not worker:
        return jsonify({"success": False, "error": {"code": "NOT_FOUND", "message": "Worker not found."}}), 404
        
    w_coords = worker.get("current_location", {}).get("coordinates", [77.5946, 12.9716])
    w_lat, w_lng = w_coords[1], w_coords[0]
    
    # Resolve issue coordinates
    issue_coords_list = []
    if issue_ids_raw:
        issue_ids = []
        for id_str in issue_ids_raw.split(","):
            p_id = parse_object_id(id_str.strip())
            if p_id:
                issue_ids.append(p_id)
        issues = list(db.issues.find({"_id": {"$in": issue_ids}}))
        
        for iss in issues:
            c = iss.get("location", {}).get("coordinates", [])
            if len(c) == 2:
                issue_coords_list.append({
                    "issue_id": str(iss["_id"]),
                    "coords": (c[1], c[0]) # lat, lng
                })
                
    if not issue_coords_list:
        # If no explicit issue_ids provided, query worker's currently active assigned jobs
        query = {"worker_id": parsed_worker_id, "status": {"$in": ["assigned", "work_started"]}}
        active_issues = list(db.issues.find(query))
        for iss in active_issues:
            c = iss.get("location", {}).get("coordinates", [])
            if len(c) == 2:
                issue_coords_list.append({
                    "issue_id": str(iss["_id"]),
                    "coords": (c[1], c[0])
                })
                
    if not issue_coords_list:
        return jsonify({"success": True, "data": []}), 200
        
    # Solve TSP nearest-neighbour optimization
    try:
        optimized_stops = route_service.optimize_multi_stop_route(
            worker_location=(w_lat, w_lng),
            issue_locations=issue_coords_list
        )
        return jsonify({"success": True, "data": optimized_stops}), 200
    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"success": False, "error": {"code": "SERVER_ERROR", "message": "An internal server error occurred."}}), 500

@map_api_bp.route('/api/public/map', methods=['GET'])
def get_public_map():
    issues = list(db.issues.find({"status": {"$nin": ["closed", "rejected"]}}, {
        "location": 1,
        "severity": 1,
        "category": 1,
        "status": 1,
        "ward": 1,
        "confirmation_count": 1
    }))
    return jsonify({"success": True, "data": serialize(issues)}), 200

@map_api_bp.route('/api/map/hotspots', methods=['GET'])
@require_auth
@require_role('officer')
def get_map_hotspots():
    # If no data exists, try running the compute_hotspots dynamically once
    hotspots = list(db.hotspots.find({}))
    if not hotspots:
        from services.prediction_service import compute_hotspots
        hotspots = compute_hotspots()
        
    return jsonify({
        "success": True,
        "data": serialize(hotspots),
        "total_closed_complaints": db.issues.count_documents({"status": "closed"})
    }), 200

@map_api_bp.route('/api/route', methods=['POST'])
@require_auth
def calculate_route():
    data = request.get_json() or {}
    origin = data.get("origin", {})
    destination = data.get("destination", {})
    
    orig_lat = origin.get("lat") if origin.get("lat") is not None else origin.get("latitude")
    orig_lng = origin.get("lng") if origin.get("lng") is not None else origin.get("longitude")
    dest_lat = destination.get("lat") if destination.get("lat") is not None else destination.get("latitude")
    dest_lng = destination.get("lng") if destination.get("lng") is not None else destination.get("longitude")
    
    if orig_lat is None or orig_lng is None or dest_lat is None or dest_lng is None:
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": "origin and destination coordinates required."}}), 400
        
    try:
        orig_lat = float(orig_lat)
        orig_lng = float(orig_lng)
        dest_lat = float(dest_lat)
        dest_lng = float(dest_lng)
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": "Coordinates must be numeric."}}), 400
        
    if not (-90 <= orig_lat <= 90) or not (-180 <= orig_lng <= 180) or not (-90 <= dest_lat <= 90) or not (-180 <= dest_lng <= 180):
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": "Coordinates out of valid geographical range."}}), 400
        
    import requests
    osrm_base = current_app.config.get("OSRM_BASE", "http://router.project-osrm.org")
    url = f"{osrm_base}/route/v1/driving/{orig_lng},{orig_lat};{dest_lng},{dest_lat}?geometries=geojson&overview=full"
    
    try:
        r = requests.get(url, timeout=4)
        if r.status_code == 200:
            res_json = r.json()
            if res_json.get("code") == "Ok" and res_json.get("routes"):
                route = res_json["routes"][0]
                dist_m = int(route.get("distance", 0))
                dur_s = int(route.get("duration", 0))
                geom = route.get("geometry", {})
                waypoints = [[coords[1], coords[0]] for coords in geom.get("coordinates", [])]
                
                if len(waypoints) > 2:
                    return jsonify({
                        "available": True,
                        "distance_meters": dist_m,
                        "duration_seconds": dur_s,
                        "geometry": waypoints
                    }), 200
    except Exception as e:
        print(f"[Route API] OSRM reachability exception: {e}")
        
    return jsonify({
        "available": False,
        "reason": "routing_service_unavailable"
    }), 200
