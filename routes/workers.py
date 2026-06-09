from datetime import datetime
from flask import Blueprint, request, jsonify, g
from bson import ObjectId
from app import db
from utils import serialize
from services.auth_service import require_role
from services.route_optimizer import optimize_route
from services.notification_service import notify_worker_room, notify_authority_room, send_email
import services.sla_service as sla_service

workers_bp = Blueprint('workers', __name__)

@workers_bp.route('/generate-route', methods=['POST'])
@require_role('authority')
def generate_route():
    data = request.get_json() or {}
    worker_id = data.get('worker_id')
    community_id = data.get('community_id')
    max_issues = int(data.get('max_issues', 10))
    
    if not worker_id or not community_id:
        return jsonify({'success': False, 'message': 'Missing worker_id or community_id', 'data': None}), 400
        
    worker = db.users.find_one({'_id': ObjectId(worker_id), 'role': 'field_worker'})
    if not worker:
        return jsonify({'success': False, 'message': 'Field worker not found', 'data': None}), 404
        
    community = db.communities.find_one({'_id': ObjectId(community_id)})
    if not community:
        return jsonify({'success': False, 'message': 'Community not found', 'data': None}), 404
        
    # Get worker coordinates
    worker_lat = worker.get('last_lat')
    worker_lng = worker.get('last_lng')
    if worker_lat is None or worker_lng is None:
        worker_lat = community['lat']
        worker_lng = community['lng']
        
    # Get validated and unassigned issues in community sorted by severity DESC, created_at ASC
    issues = list(db.issues.find({
        'community_id': ObjectId(community_id),
        'status': 'validated',
        'assigned_to': None
    }).sort([('severity', -1), ('created_at', 1)]).limit(max_issues))
    
    if not issues:
        return jsonify({'success': False, 'message': 'No validated, unassigned issues found to route', 'data': None}), 400
        
    # Run optimizer
    opt_res = optimize_route(worker_lat, worker_lng, issues)
    
    # Mark any existing active route for this worker as completed
    db.routes.update_many(
        {'worker_id': ObjectId(worker_id), 'status': 'active'},
        {'$set': {'status': 'completed', 'completed_at': datetime.utcnow()}}
    )
    
    # Save new route
    now = datetime.utcnow()
    route_doc = {
        "worker_id": ObjectId(worker_id),
        "community_id": ObjectId(community_id),
        "issue_ids": opt_res['ordered_issue_ids'],
        "optimized_order": opt_res['ordered_issue_ids'],
        "waypoints": opt_res['waypoints'],
        "total_distance_km": opt_res['total_distance_km'],
        "estimated_duration_min": opt_res['estimated_duration_min'],
        "status": "active",
        "created_at": now,
        "completed_at": None
    }
    
    route_id = db.routes.insert_one(route_doc).inserted_id
    
    # Update issues to assigned
    issue_obj_ids = [ObjectId(iid) for iid in opt_res['ordered_issue_ids'] if iid != 'depot']
    db.issues.update_many(
        {'_id': {'$in': issue_obj_ids}},
        {
            '$set': {
                'status': 'assigned',
                'assigned_to': ObjectId(worker_id),
                'assigned_at': now
            },
            '$push': {
                'status_history': {
                    'status': 'assigned',
                    'changed_by': ObjectId(g.user['user_id']),
                    'timestamp': now,
                    'note': f"Assigned to field worker {worker['name']}."
                }
            }
        }
    )
    
    # Notify worker room via Socket
    socket_data = {
        'route_id': str(route_id),
        'waypoints': opt_res['waypoints'],
        'total_distance_km': opt_res['total_distance_km']
    }
    notify_worker_room(worker_id, 'route_assigned', socket_data)
    
    # Email worker with route summary
    email_body = f"""
    <h3>SmartCivic Route Assignment</h3>
    <p>Hi {worker['name']},</p>
    <p>You have been assigned a new service route containing <strong>{len(issue_obj_ids)}</strong> issues.</p>
    <ul>
        <li><strong>Total Distance:</strong> {opt_res['total_distance_km']} km</li>
        <li><strong>Estimated Duration:</strong> {opt_res['estimated_duration_min']} min</li>
    </ul>
    <p>Please open the app to trace your route waypoints and check deadlines.</p>
    """
    send_email(worker['email'], "SmartCivic: New Route Assigned", email_body)
    
    return jsonify({
        'success': True,
        'message': 'Route generated and assigned successfully',
        'data': {
            'route_id': str(route_id),
            'waypoints': opt_res['waypoints'],
            'total_distance_km': opt_res['total_distance_km'],
            'estimated_duration_min': opt_res['estimated_duration_min']
        }
    }), 201

@workers_bp.route('/my-route', methods=['GET'])
@require_role('field_worker')
def my_route():
    worker_id = ObjectId(g.user['user_id'])
    route = db.routes.find_one({'worker_id': worker_id, 'status': 'active'})
    
    if not route:
        return jsonify({'success': True, 'message': 'No active route found', 'data': None}), 200
        
    # Enrich waypoints with issue details and SLA status
    enriched_waypoints = []
    for wp in route.get('waypoints', []):
        issue_id = wp.get('issue_id')
        if issue_id and issue_id != 'depot':
            issue = db.issues.find_one({'_id': ObjectId(issue_id)})
            if issue:
                wp['description'] = issue.get('description', '')
                wp['status'] = issue.get('status')
                wp['sla_status'] = sla_service.get_sla_status(issue)
                wp['images'] = issue.get('images', [])
        enriched_waypoints.append(wp)
        
    route['waypoints'] = enriched_waypoints
    return jsonify({
        'success': True,
        'message': 'Active route retrieved',
        'data': serialize(route)
    }), 200

@workers_bp.route('/update-location', methods=['PUT'])
@require_role('field_worker')
def update_location():
    data = request.get_json() or {}
    lat = data.get('lat')
    lng = data.get('lng')
    
    if lat is None or lng is None:
        return jsonify({'success': False, 'message': 'Missing lat or lng', 'data': None}), 400
        
    worker_id = ObjectId(g.user['user_id'])
    name = g.user['name']
    community_id = g.user['community_id']
    
    # Save worker location to user model
    db.users.update_one(
        {'_id': worker_id},
        {'$set': {'last_lat': float(lat), 'last_lng': float(lng)}}
    )
    
    # Emit Socket location update to authority room
    socket_data = {
        'worker_id': str(worker_id),
        'name': name,
        'lat': float(lat),
        'lng': float(lng),
        'community_id': community_id
    }
    notify_authority_room(community_id, 'worker_location', socket_data)
    
    return jsonify({'success': True, 'message': 'Location updated successfully', 'data': None}), 200

@workers_bp.route('/stats/<worker_id>', methods=['GET'])
@require_role('authority', 'field_worker')
def worker_stats(worker_id):
    issues = list(db.issues.find({'assigned_to': ObjectId(worker_id)}))
    
    total_assigned = len(issues)
    resolved_issues = [i for i in issues if i.get('status') == 'resolved']
    total_resolved = len(resolved_issues)
    
    resolution_durations = []
    for i in resolved_issues:
        a_at = i.get('assigned_at')
        r_at = i.get('resolved_at')
        if a_at and r_at:
            if isinstance(a_at, str):
                a_at = datetime.fromisoformat(a_at.replace('Z', '+00:00')).replace(tzinfo=None)
            if isinstance(r_at, str):
                r_at = datetime.fromisoformat(r_at.replace('Z', '+00:00')).replace(tzinfo=None)
            hours = (r_at - a_at).total_seconds() / 3600
            resolution_durations.append(hours)
            
    avg_resolution_hours = round(sum(resolution_durations) / len(resolution_durations), 2) if resolution_durations else 0.0
    
    sla_compliant_count = 0
    for i in resolved_issues:
        deadline = i.get('sla_deadline')
        r_at = i.get('resolved_at')
        if deadline and r_at:
            if isinstance(deadline, str):
                deadline = datetime.fromisoformat(deadline.replace('Z', '+00:00')).replace(tzinfo=None)
            if isinstance(r_at, str):
                r_at = datetime.fromisoformat(r_at.replace('Z', '+00:00')).replace(tzinfo=None)
            if r_at <= deadline:
                sla_compliant_count += 1
                
    sla_breach_count = sum(1 for i in issues if i.get('sla_breached', False))
    
    issues_by_category = {}
    for i in issues:
        cat = i.get('category', 'other')
        issues_by_category[cat] = issues_by_category.get(cat, 0) + 1
        
    resolved_this_month = 0
    now = datetime.utcnow()
    for i in resolved_issues:
        r_at = i.get('resolved_at')
        if r_at:
            if isinstance(r_at, str):
                r_at = datetime.fromisoformat(r_at.replace('Z', '+00:00')).replace(tzinfo=None)
            if r_at.year == now.year and r_at.month == now.month:
                resolved_this_month += 1
                
    # Average resolution time by category
    cat_durations = {}
    for i in resolved_issues:
        cat = i.get('category', 'other')
        a_at = i.get('assigned_at')
        r_at = i.get('resolved_at')
        if a_at and r_at:
            if isinstance(a_at, str):
                a_at = datetime.fromisoformat(a_at.replace('Z', '+00:00')).replace(tzinfo=None)
            if isinstance(r_at, str):
                r_at = datetime.fromisoformat(r_at.replace('Z', '+00:00')).replace(tzinfo=None)
            hours = (r_at - a_at).total_seconds() / 3600
            if cat not in cat_durations:
                cat_durations[cat] = []
            cat_durations[cat].append(hours)
            
    avg_resolution_time_by_category = {cat: round(sum(durs)/len(durs), 2) for cat, durs in cat_durations.items()}
    
    stats_data = {
        'total_assigned': total_assigned,
        'total_resolved': total_resolved,
        'avg_resolution_hours': avg_resolution_hours,
        'sla_compliant_count': sla_compliant_count,
        'sla_breach_count': sla_breach_count,
        'issues_by_category': issues_by_category,
        'resolved_this_month': resolved_this_month,
        'avg_resolution_time_by_category': avg_resolution_time_by_category
    }
    
    return jsonify({
        'success': True,
        'message': 'Worker stats retrieved successfully',
        'data': stats_data
    }), 200

@workers_bp.route('/route/<route_id>/cancel', methods=['PUT'])
@require_role('authority')
def cancel_route(route_id):
    route = db.routes.find_one({'_id': ObjectId(route_id), 'status': 'active'})
    if not route:
        return jsonify({'success': False, 'message': 'Active route not found', 'data': None}), 404
        
    issue_ids = [ObjectId(iid) for iid in route.get('issue_ids', []) if iid != 'depot']
    
    now = datetime.utcnow()
    db.issues.update_many(
        {'_id': {'$in': issue_ids}},
        {
            '$set': {
                'status': 'validated',
                'assigned_to': None,
                'assigned_at': None
            },
            '$push': {
                'status_history': {
                    'status': 'validated',
                    'changed_by': ObjectId(g.user['user_id']),
                    'timestamp': now,
                    'note': "Route unassigned by authority."
                }
            }
        }
    )
    
    db.routes.update_one(
        {'_id': ObjectId(route_id)},
        {'$set': {'status': 'cancelled', 'completed_at': now}}
    )
    
    notify_worker_room(str(route['worker_id']), 'route_cancelled', {'route_id': route_id})
    
    return jsonify({'success': True, 'message': 'Route unassigned successfully', 'data': None}), 200

