from datetime import datetime
from flask import Blueprint, request, jsonify, g
from bson import ObjectId
from app import db
from utils import serialize
from services.auth_service import require_role
from services.score_service import check_stale_issues
from services.sla_service import check_and_flag_sla_breaches

communities_bp = Blueprint('communities', __name__)

@communities_bp.route('/', methods=['GET'])
def list_communities():
    communities = list(db.communities.find().sort([('community_score', -1)]))
    return jsonify({
        'success': True,
        'message': 'Communities retrieved',
        'data': serialize(communities)
    }), 200

@communities_bp.route('/<community_id>/score', methods=['GET'])
def get_community_score(community_id):
    # Run cron-like checks to update scores in real-time on query
    check_stale_issues()
    check_and_flag_sla_breaches()
    
    community = db.communities.find_one({'_id': ObjectId(community_id)})
    if not community:
        return jsonify({'success': False, 'message': 'Community not found', 'data': None}), 404
        
    sla_breached_count = db.issues.count_documents({
        'community_id': ObjectId(community_id),
        'sla_breached': True
    })
    
    score_data = {
        'community_score': community.get('community_score', 100),
        'open_issues': community.get('open_issues', 0),
        'resolved_issues': community.get('resolved_issues', 0),
        'total_issues': community.get('total_issues', 0),
        'score_history': community.get('score_history', [])[-30:],
        'sla_breached_count': sla_breached_count
    }
    
    return jsonify({
        'success': True,
        'message': 'Community score details retrieved',
        'data': serialize(score_data)
    }), 200

@communities_bp.route('/create', methods=['POST'])
@require_role('authority')
def create_community():
    data = request.get_json() or {}
    name = data.get('name')
    city = data.get('city')
    state = data.get('state')
    lat = data.get('lat')
    lng = data.get('lng')
    boundary_radius_km = data.get('boundary_radius_km')
    
    if not all([name, city, state, lat, lng, boundary_radius_km]):
        return jsonify({'success': False, 'message': 'Missing required fields', 'data': None}), 400
        
    try:
        lat = float(lat)
        lng = float(lng)
        boundary_radius_km = float(boundary_radius_km)
    except ValueError:
        return jsonify({'success': False, 'message': 'Invalid latitude, longitude or boundary radius', 'data': None}), 400
        
    community_doc = {
        "name": name.strip(),
        "city": city.strip(),
        "state": state.strip(),
        "lat": lat,
        "lng": lng,
        "boundary_radius_km": boundary_radius_km,
        "community_score": 100,
        "total_issues": 0,
        "resolved_issues": 0,
        "open_issues": 0,
        "created_at": datetime.utcnow(),
        "score_history": []
    }
    
    inserted_id = db.communities.insert_one(community_doc).inserted_id
    
    return jsonify({
        'success': True,
        'message': 'Community created successfully',
        'data': {
            'community_id': str(inserted_id)
        }
    }), 201
