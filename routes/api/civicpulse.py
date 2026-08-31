"""
SmartCivic+ — CivicPulse Prediction API Blueprint
Exposes the proactive maintenance queue and per-segment decay predictions.
"""
from flask import Blueprint, request, jsonify, g
from routes.auth import require_auth, require_role
from services.civicpulse_service import (
    get_proactive_maintenance_queue,
    get_segment_prediction,
    compute_civicpulse_predictions,
)
from utils import serialize

civicpulse_api_bp = Blueprint('civicpulse_api', __name__)


@civicpulse_api_bp.route('/api/civicpulse/queue', methods=['GET'])
@require_auth
@require_role('officer')
def get_maintenance_queue():
    """
    Returns segments predicted to fail soonest.
    Query params:
      ward   — filter to a specific ward (optional)
      limit  — max results, default 20
    """
    ward = request.args.get("ward")
    limit = int(request.args.get("limit", 20))
    limit = max(1, min(limit, 100))

    queue = get_proactive_maintenance_queue(ward=ward, limit=limit)
    return jsonify({"success": True, "data": serialize(queue), "count": len(queue)}), 200


@civicpulse_api_bp.route('/api/civicpulse/segment/<segment_id>', methods=['GET'])
@require_auth
@require_role('officer')
def get_segment_decay(segment_id):
    """Returns the decay prediction for a single infrastructure segment."""
    pred = get_segment_prediction(segment_id)
    if not pred:
        return jsonify({"success": False,
                        "error": {"code": "NOT_FOUND",
                                  "message": "No prediction computed for this segment yet. "
                                             "Run /api/civicpulse/trigger to compute."}}), 404
    return jsonify({"success": True, "data": serialize(pred)}), 200


@civicpulse_api_bp.route('/api/civicpulse/trigger', methods=['POST'])
@require_auth
@require_role('officer')
def trigger_prediction_sweep():
    """
    Manually triggers a full CivicPulse prediction sweep.
    Useful after seeding new infrastructure segments or for on-demand refresh.
    Heavy operation — rate-limited to officers only.
    """
    try:
        predictions = compute_civicpulse_predictions()
        return jsonify({
            "success": True,
            "message": f"CivicPulse sweep completed. {len(predictions)} segments processed.",
            "data": {
                "segments_processed": len(predictions),
                "critical": sum(1 for p in predictions if p["risk_band"] == "CRITICAL"),
                "high": sum(1 for p in predictions if p["risk_band"] == "HIGH"),
                "medium": sum(1 for p in predictions if p["risk_band"] == "MEDIUM"),
                "low": sum(1 for p in predictions if p["risk_band"] == "LOW"),
            }
        }), 200
    except Exception as e:
        return jsonify({"success": False,
                        "error": {"code": "SERVER_ERROR", "message": str(e)}}), 500
