"""
SmartCivic+ — What-If Simulation API Blueprint
Exposes simulation_service worker-addition and category-priority-shift endpoints.
"""
from flask import Blueprint, request, jsonify, g
from routes.auth import require_auth, require_role
from services import simulation_service
from utils import serialize

simulation_api_bp = Blueprint('simulation_api', __name__)

@simulation_api_bp.route('/api/simulate/worker-addition', methods=['POST'])
@require_auth
@require_role('officer')
def api_simulate_worker_addition():
    data = request.get_json() or {}
    ward = data.get("ward", "")
    department = data.get("department", "")
    additional_workers = int(data.get("additional_workers", 1))
    if additional_workers < 1 or additional_workers > 50:
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR",
                        "message": "additional_workers must be between 1 and 50."}}), 422
    result = simulation_service.simulate_worker_addition(ward, department, additional_workers)
    return jsonify({"success": True, "data": result}), 200

@simulation_api_bp.route('/api/simulate/category-priority', methods=['POST'])
@require_auth
@require_role('officer')
def api_simulate_category_priority():
    data = request.get_json() or {}
    category = data.get("category", "")
    VALID = ["road", "water", "electricity", "sanitation", "drainage"]
    if category not in VALID:
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR",
                        "message": f"category must be one of: {VALID}"}}), 422
    result = simulation_service.simulate_category_priority_shift(category)
    return jsonify({"success": True, "data": result}), 200
