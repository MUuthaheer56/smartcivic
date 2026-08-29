from flask import Blueprint, request, jsonify
from ai.analytics import get_severity_heatmap, calculate_civic_risk_scores, get_worker_performance_stats
from ai.coordination.coordination_analyzer import compute_coordination_failures
from ai.trust.civic_trust_scorer import compute_ward_trust_scores

analytics_bp = Blueprint('analytics', __name__)

@analytics_bp.route('/heatmap', methods=['GET'])
def heatmap_endpoint():
    """
    GET /api/analytics/heatmap
    Parameters: category, severity, status
    """
    category = request.args.get('category')
    severity = request.args.get('severity')
    status = request.args.get('status')
    
    data = get_severity_heatmap(category, severity, status)
    return jsonify(data), 200

@analytics_bp.route('/risk', methods=['GET'])
def risk_endpoint():
    """
    GET /api/analytics/risk
    Parameters: ward
    """
    ward = request.args.get('ward')
    data = calculate_civic_risk_scores(ward)
    return jsonify(data), 200

@analytics_bp.route('/worker-performance', methods=['GET'])
def worker_performance_endpoint():
    """
    GET /api/analytics/worker-performance
    Parameters: worker_id
    """
    worker_id = request.args.get('worker_id')
    if not worker_id:
        return jsonify({"success": False, "message": "Missing worker_id parameter"}), 400
        
    data = get_worker_performance_stats(worker_id)
    return jsonify(data), 200

@analytics_bp.route('/coordination-failures', methods=['GET'])
def get_coordination_failures():
    """
    GET /api/analytics/coordination-failures
    """
    from app import db
    failures = list(db.coordination_failures.find(
        {}, {"_id": 0}
    ).sort("cfi_score", -1).limit(50))
    return jsonify(failures), 200

@analytics_bp.route('/ward-trust', methods=['GET'])
def get_ward_trust():
    """
    GET /api/analytics/ward-trust
    """
    from app import db
    scores = list(db.ward_trust_scores.find(
        {}, {"_id": 0}
    ).sort("trust_score", -1))
    return jsonify(scores), 200
