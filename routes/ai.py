from flask import Blueprint, request, jsonify, g
from bson import ObjectId
import base64
import os
from services.auth_service import require_auth
from ai.detector import detect_road_damage
from ai.quality import check_image_quality
from ai.severity import estimate_severity
from ai.confidence import route_confidence_threshold
from ai.duplicate import check_geospatial_duplicate, check_visual_duplicate
from ai.repair import verify_repair_performance
from ai.nlp import classify_complaint_text

# 10 features imports
from ai.footpath.encroachment_detector import compute_footpath_impact
from ai.dump.dump_age_estimator import extract_aging_features, estimate_dump_age
from ai.lakes.lake_boundary_checker import check_lake_buffer
from ai.construction.safety_detector import detect_construction_hazard
from ai.construction.permit_checker import check_construction_permit
from ai.drain.drain_predictor import run_drain_prediction

ai_bp = Blueprint('ai', __name__)

@ai_bp.route('/analyze-image', methods=['POST'])
def analyze_image_endpoint():
    """
    POST /api/ai/analyze-image
    Input: image (file) or base64 data
    """
    file = request.files.get('image')
    if file:
        image_bytes = file.read()
    else:
        # Check base64 input
        data = request.get_json() or {}
        image_b64 = data.get('image')
        if not image_b64:
            return jsonify({"success": False, "message": "No image payload provided"}), 400
        try:
            # Strip header if present
            if "," in image_b64:
                image_b64 = image_b64.split(",")[1]
            image_bytes = base64.b64decode(image_b64)
        except Exception:
            return jsonify({"success": False, "message": "Invalid base64 payload"}), 400
            
    try:
        results = detect_road_damage(image_bytes)
        return jsonify(results), 200
    except ValueError as e:
        return jsonify({"success": False, "message": str(e)}), 400

@ai_bp.route('/check-image-quality', methods=['POST'])
def check_quality_endpoint():
    """
    POST /api/ai/check-image-quality
    """
    file = request.files.get('image')
    if file:
        image_bytes = file.read()
    else:
        data = request.get_json() or {}
        image_b64 = data.get('image')
        if not image_b64:
            return jsonify({"success": False, "message": "No image payload provided"}), 400
        try:
            if "," in image_b64:
                image_b64 = image_b64.split(",")[1]
            image_bytes = base64.b64decode(image_b64)
        except Exception:
            return jsonify({"success": False, "message": "Invalid base64 payload"}), 400
            
    res = check_image_quality(image_bytes)
    return jsonify(res), 200

@ai_bp.route('/classify-complaint', methods=['POST'])
def classify_complaint_endpoint():
    """
    POST /api/ai/classify-complaint
    """
    data = request.get_json() or {}
    description = data.get('description')
    if not description:
        return jsonify({"success": False, "message": "No description provided"}), 400
        
    res = classify_complaint_text(description)
    return jsonify(res), 200

@ai_bp.route('/check-duplicate', methods=['POST'])
def check_duplicate_endpoint():
    """
    POST /api/ai/check-duplicate
    """
    data = request.get_json() or {}
    lat = data.get('lat')
    lng = data.get('lng')
    category = data.get('category')
    community_id = data.get('community_id')
    
    if lat is None or lng is None or not category or not community_id:
        return jsonify({"success": False, "message": "Missing required fields: lat, lng, category, community_id"}), 400
        
    matches = check_geospatial_duplicate(float(lat), float(lng), category, community_id)
    is_duplicate = len(matches) > 0
    return jsonify({
        "is_duplicate": is_duplicate,
        "matches": matches
    }), 200

@ai_bp.route('/check-image-similarity', methods=['POST'])
def check_similarity_endpoint():
    """
    POST /api/ai/check-image-similarity
    """
    file = request.files.get('image')
    if file:
        image_bytes = file.read()
    else:
        # Check base64 input or embedding
        data = request.get_json() or {}
        image_b64 = data.get('image')
        if not image_b64:
            return jsonify({"success": False, "message": "No image provided"}), 400
        try:
            if "," in image_b64:
                image_b64 = image_b64.split(",")[1]
            image_bytes = base64.b64decode(image_b64)
        except Exception:
            return jsonify({"success": False, "message": "Invalid base64 payload"}), 400
            
    data = request.get_json() or {}
    # Read nearby IDs from parameters or json
    nearby_ids = request.form.getlist('nearby_complaint_ids') or data.get('nearby_complaint_ids') or []
    
    res = check_visual_duplicate(image_bytes, nearby_ids)
    return jsonify({"similarities": res}), 200

@ai_bp.route('/compute-confidence', methods=['POST'])
def compute_confidence_endpoint():
    """
    POST /api/ai/compute-confidence
    """
    data = request.get_json() or {}
    ai_conf = data.get('ai_confidence', 0.5)
    img_qual = data.get('image_quality', 50)
    loc_score = data.get('location_score', 0.5)
    comm_res = data.get('community_result', 0.5)
    hist_score = data.get('historical_score', 0.5)
    
    # Weighted fusion score:
    # AI detection confidence: 35%
    # Image quality score: 20%
    # Geospatial consistency: 15%
    # Community verification result: 20%
    # Historical evidence: 10%
    civic_score = (
        (ai_conf * 0.35) +
        ((img_qual / 100.0) * 0.20) +
        (loc_score * 0.15) +
        (comm_res * 0.20) +
        (hist_score * 0.10)
    )
    
    level = "LOW"
    if civic_score >= 0.75:
        level = "HIGH"
    elif civic_score >= 0.40:
        level = "MEDIUM"
        
    return jsonify({
        "civic_confidence": round(civic_score, 3),
        "level": level
    }), 200

@ai_bp.route('/verify-repair', methods=['POST'])
def verify_repair_endpoint():
    """
    POST /api/ai/verify-repair
    """
    complaint_id = request.form.get('complaint_id')
    file = request.files.get('after_image')
    
    if not complaint_id or not file:
        return jsonify({"success": False, "message": "Missing complaint_id or after_image file"}), 400
        
    # Read image bytes and run analysis
    after_bytes = file.read()
    
    # Check if issue exists in database to get before confidence
    from app import db
    issue = db.issues.find_one({'_id': ObjectId(complaint_id)})
    if not issue:
        return jsonify({"success": False, "message": "Complaint not found"}), 404
        
    before_conf = issue.get('ai_confidence', 0.95)
    
    # Run mock detection on the new after image
    detection = detect_road_damage(after_bytes)
    after_conf = detection.get('confidence', 0.12)
    
    res = verify_repair_performance(complaint_id, before_conf, after_conf)
    return jsonify(res), 200

@ai_bp.route('/route-complaint', methods=['POST'])
def route_complaint_endpoint():
    """
    POST /api/ai/route-complaint
    """
    data = request.get_json() or {}
    confidence = data.get('confidence')
    if confidence is None:
        return jsonify({"success": False, "message": "No confidence score provided"}), 400
        
    res = route_confidence_threshold(float(confidence))
    return jsonify(res), 200

@ai_bp.route('/analyze-footpath', methods=['POST'])
def analyze_footpath_endpoint():
    """
    POST /api/ai/analyze-footpath
    """
    file = request.files.get('image')
    if file:
        image_bytes = file.read()
    else:
        # Check base64 input
        data = request.get_json() or {}
        image_b64 = data.get('image')
        if not image_b64:
            return jsonify({"success": False, "message": "No image payload provided"}), 400
        try:
            if "," in image_b64:
                image_b64 = image_b64.split(",")[1]
            image_bytes = base64.b64decode(image_b64)
        except Exception:
            return jsonify({"success": False, "message": "Invalid base64 payload"}), 400
            
    # Read lat/lng
    lat = float(request.form.get('lat', 12.9716))
    lng = float(request.form.get('lng', 77.5946))
    
    # Run mock YOLO detections for footpath blocking
    # A single mock detection of a parked motorcycle
    yolo_detections = [{
        "class": "motorcycle",
        "bbox": [150.0, 400.0, 300.0, 600.0],
        "confidence": 0.92
    }]
    
    res = compute_footpath_impact(yolo_detections, 640, 640, lat, lng)
    return jsonify(res), 200

@ai_bp.route('/estimate-dump-age', methods=['POST'])
def estimate_dump_age_endpoint():
    """
    POST /api/ai/estimate-dump-age
    """
    file = request.files.get('image')
    # Save the file temporarily if present to run cv2 analysis
    temp_path = "temp_dump.jpg"
    if file:
        file.save(temp_path)
    else:
        # Create empty image file for test fallback
        with open(temp_path, "wb") as f:
            f.write(b"")
            
    features = extract_aging_features(temp_path)
    res = estimate_dump_age(features)
    
    # Clean up temp file
    if os.path.exists(temp_path):
        os.remove(temp_path)
        
    return jsonify(res), 200

@ai_bp.route('/check-lake-boundary', methods=['POST'])
def check_lake_boundary_endpoint():
    """
    POST /api/ai/check-lake-boundary
    """
    data = request.get_json() or {}
    lat = data.get('lat')
    lng = data.get('lng')
    if lat is None or lng is None:
        return jsonify({"success": False, "message": "Missing lat/lng"}), 400
        
    res = check_lake_buffer(float(lat), float(lng))
    return jsonify(res), 200

@ai_bp.route('/check-construction-safety', methods=['POST'])
def check_construction_safety_endpoint():
    """
    POST /api/ai/check-construction-safety
    """
    file = request.files.get('image')
    temp_path = "temp_safety.jpg"
    if file:
        file.save(temp_path)
    else:
        with open(temp_path, "wb") as f:
            f.write(b"")
            
    lat = float(request.form.get('lat', 12.9716))
    lng = float(request.form.get('lng', 77.5946))
    
    from app import db
    hazard = detect_construction_hazard(temp_path)
    permit = check_construction_permit(lat, lng, db)
    
    if os.path.exists(temp_path):
        os.remove(temp_path)
        
    return jsonify({**hazard, **permit}), 200

@ai_bp.route('/drain-risk', methods=['GET'])
def get_drain_risk():
    """
    GET /api/ai/drain-risk
    """
    from app import db
    risks = list(db.drain_risk.find(
        {"risk_score": {"$gt": 0}},
        {"_id": 0}
    ).sort("risk_score", -1))
    return jsonify(risks), 200

