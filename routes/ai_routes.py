"""
SmartCivic AI Routes — /api/ai/*
All endpoints are authority-only except /analyze-image and /classify-text.
"""
from flask import Blueprint, request, jsonify, g
from services.auth_service import require_auth, require_role, require_verified

ai_bp = Blueprint('ai', __name__)


@ai_bp.route('/analyze-image', methods=['POST'])
@require_verified
def analyze_image_route():
    """
    POST /api/ai/analyze-image
    Accepts multipart image file, returns quality gate result + severity estimate.
    """
    from ai.image_analyzer import analyze_image

    img_file = request.files.get('image')
    if not img_file:
        return jsonify({'success': False, 'message': 'No image file provided', 'data': None}), 400

    try:
        image_bytes = img_file.read()
        result = analyze_image(image_bytes)
        return jsonify({'success': True, 'message': 'Image analyzed', 'data': result}), 200
    except Exception as e:
        return jsonify({'success': False, 'message': f'Analysis error: {str(e)}', 'data': None}), 500


@ai_bp.route('/classify-text', methods=['POST'])
@require_verified
def classify_text_route():
    """
    POST /api/ai/classify-text
    Body: { "title": str, "description": str }
    Returns: category, department, confidence, urgency_flag
    """
    from ai.nlp_classifier import classify_issue

    data = request.get_json() or {}
    title = data.get('title', '')
    description = data.get('description', '')

    if not title:
        return jsonify({'success': False, 'message': 'title is required', 'data': None}), 400

    result = classify_issue(title, description)
    return jsonify({'success': True, 'message': 'Classification complete', 'data': result}), 200


@ai_bp.route('/drain-risk/<community_id>', methods=['GET'])
@require_role('authority')
def drain_risk_route(community_id):
    """
    GET /api/ai/drain-risk/<community_id>
    Returns drain blockage risk scores for all known drains near the community.
    """
    from ai.drain_predictor import compute_drain_risks
    from flask import current_app

    api_key = current_app.config.get('OPENWEATHER_API_KEY', '')
    results = compute_drain_risks(community_id, api_key)
    return jsonify({'success': True, 'message': 'Drain risk computed', 'data': results}), 200


@ai_bp.route('/trust-score/<community_id>', methods=['GET'])
@require_auth
def trust_score_route(community_id):
    """
    GET /api/ai/trust-score/<community_id>
    Returns Civic Trust Score with component breakdown.
    """
    from ai.trust_scorer import compute_trust_score

    result = compute_trust_score(community_id)
    return jsonify({'success': True, 'message': 'Trust score computed', 'data': result}), 200


@ai_bp.route('/anomalies/<community_id>', methods=['GET'])
@require_role('authority')
def anomaly_route(community_id):
    """
    GET /api/ai/anomalies/<community_id>
    Returns statistical anomalies in issue reporting by category.
    """
    from ai.anomaly_detector import detect_anomalies

    lookback = int(request.args.get('lookback_days', 30))
    results = detect_anomalies(community_id, lookback)
    return jsonify({'success': True, 'message': 'Anomaly detection complete', 'data': results}), 200


@ai_bp.route('/validate-noise', methods=['POST'])
@require_verified
def validate_noise_route():
    """
    POST /api/ai/validate-noise
    Body: { "db_spl": float, "zone_type": str, "is_night": bool }
    Returns CPCB compliance status + severity estimate.
    """
    from ai.noise_validator import validate_noise

    data = request.get_json() or {}
    db_spl = data.get('db_spl')
    zone_type = data.get('zone_type', 'residential')
    is_night = bool(data.get('is_night', False))

    if db_spl is None:
        return jsonify({'success': False, 'message': 'db_spl is required', 'data': None}), 400

    try:
        db_spl = float(db_spl)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'db_spl must be a number', 'data': None}), 400

    result = validate_noise(db_spl, zone_type, is_night)
    return jsonify({'success': True, 'message': 'Noise validated', 'data': result}), 200
