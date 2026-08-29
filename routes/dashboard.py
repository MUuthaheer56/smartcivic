from datetime import datetime
from flask import Blueprint, request, jsonify, g
from bson import ObjectId
from app import db
from utils import serialize
from services.auth_service import require_auth, require_role
from services.score_service import check_stale_issues
from services.sla_service import check_and_flag_sla_breaches
import services.clustering_service as clustering_service

dashboard_bp = Blueprint('dashboard', __name__)

def get_community_dashboard_data(community_id):
    community = db.communities.find_one({'_id': ObjectId(community_id)})
    if not community:
        return None
        
    now = datetime.utcnow()
    
    # 1. Total/Resolved/Open calculations
    total_issues = db.issues.count_documents({'community_id': ObjectId(community_id)})
    resolved_issues_count = db.issues.count_documents({'community_id': ObjectId(community_id), 'status': 'resolved'})
    open_issues_count = db.issues.count_documents({'community_id': ObjectId(community_id), 'status': {'$in': ['pending_validation', 'validated', 'assigned', 'in_progress']}})
    
    resolution_rate = round((resolved_issues_count / total_issues * 100), 2) if total_issues > 0 else 100.0
    
    # 2. Avg resolution time
    resolved_issues = list(db.issues.find({'community_id': ObjectId(community_id), 'status': 'resolved'}))
    res_times = []
    for iss in resolved_issues:
        c_at = iss.get('created_at')
        r_at = iss.get('resolved_at')
        if c_at and r_at:
            if isinstance(c_at, str):
                c_at = datetime.fromisoformat(c_at.replace('Z', '+00:00')).replace(tzinfo=None)
            if isinstance(r_at, str):
                r_at = datetime.fromisoformat(r_at.replace('Z', '+00:00')).replace(tzinfo=None)
            res_times.append((r_at - c_at).total_seconds() / 3600)
    avg_resolution_time = round(sum(res_times) / len(res_times), 2) if res_times else 0.0
    
    # 3. Categorized / Status Breakdown
    all_issues = list(db.issues.find({'community_id': ObjectId(community_id)}))
    issues_by_category = {}
    issues_by_status = {}
    for iss in all_issues:
        cat = iss.get('category', 'other')
        stat = iss.get('status', 'pending_validation')
        issues_by_category[cat] = issues_by_category.get(cat, 0) + 1
        issues_by_status[stat] = issues_by_status.get(stat, 0) + 1
        
    # 4. Top reporters
    reporter_counts = {}
    for iss in all_issues:
        rep_id = str(iss.get('reporter_id'))
        is_anon = iss.get('is_anonymous', False)
        if is_anon:
            reporter_counts['Anonymous'] = reporter_counts.get('Anonymous', 0) + 1
        else:
            reporter_counts[rep_id] = reporter_counts.get(rep_id, 0) + 1
            
    top_reporters = []
    for key, count in reporter_counts.items():
        if key == 'Anonymous':
            top_reporters.append({'name_or_anon': 'Anonymous Resident', 'count': count})
        else:
            u = db.users.find_one({'_id': ObjectId(key)})
            name = u['name'] if u else 'Deleted Resident'
            top_reporters.append({'name_or_anon': name, 'count': count})
    top_reporters = sorted(top_reporters, key=lambda x: x['count'], reverse=True)[:5]
    
    # 5. Recent Issues (last 10)
    recent_issues = list(db.issues.find({'community_id': ObjectId(community_id)}).sort([('created_at', -1)]).limit(10))
    for iss in recent_issues:
        if iss.get('is_anonymous'):
            iss['reporter_name'] = "Anonymous Resident"
        else:
            rep = db.users.find_one({'_id': iss.get('reporter_id')})
            iss['reporter_name'] = rep['name'] if rep else "Unknown Resident"
            
    # 6. SLA status summary
    on_time = db.issues.count_documents({
        'community_id': ObjectId(community_id),
        'status': {'$in': ['pending_validation', 'validated', 'assigned', 'in_progress']},
        'sla_deadline': {'$gte': now},
        'sla_breached': {'$ne': True}
    })
    overdue = db.issues.count_documents({
        'community_id': ObjectId(community_id),
        'status': {'$in': ['pending_validation', 'validated', 'assigned', 'in_progress']},
        'sla_deadline': {'$lt': now}
    })
    breached = db.issues.count_documents({
        'community_id': ObjectId(community_id),
        'sla_breached': True
    })
    
    # 7. Active announcements
    active_announcements = list(db.announcements.find({
        'community_id': ObjectId(community_id),
        'is_active': True,
        '$or': [
            {'expires_at': None},
            {'expires_at': {'$gt': now}}
        ]
    }).sort([('created_at', -1)]))
    
    return {
        'community_score': community.get('community_score', 100),
        'score_trend': community.get('score_history', [])[-30:],
        'issues_by_category': issues_by_category,
        'issues_by_status': issues_by_status,
        'resolution_rate': resolution_rate,
        'avg_resolution_time_hours': avg_resolution_time,
        'top_reporters': top_reporters,
        'recent_issues': serialize(recent_issues),
        'sla_status_summary': {
            'on_time': on_time,
            'overdue': overdue,
            'breached': breached
        },
        'active_announcements': serialize(active_announcements)
    }

@dashboard_bp.route('/community/<community_id>', methods=['GET'])
@require_auth
def community_dashboard(community_id):
    dashboard_data = get_community_dashboard_data(community_id)
    if dashboard_data is None:
        return jsonify({'success': False, 'message': 'Community not found', 'data': None}), 404
        
    return jsonify({
        'success': True,
        'message': 'Community dashboard statistics retrieved',
        'data': dashboard_data
    }), 200

@dashboard_bp.route('/authority/<community_id>', methods=['GET'])
@require_role('authority')
def authority_dashboard(community_id):
    base_data = get_community_dashboard_data(community_id)
    if base_data is None:
        return jsonify({'success': False, 'message': 'Community not found', 'data': None}), 404
    
    # 2. Count of pending users
    pending_users_count = db.users.count_documents({
        'community_id': ObjectId(community_id),
        'is_verified': False
    })
    
    # 3. Active workers list
    workers = list(db.users.find({
        'community_id': ObjectId(community_id),
        'role': 'field_worker',
        'is_verified': True
    }))
    active_workers = []
    for w in workers:
        active_issues_count = db.issues.count_documents({
            'assigned_to': w['_id'],
            'status': {'$in': ['assigned', 'in_progress']}
        })
        active_workers.append({
            'id': str(w['_id']),
            'name': w['name'],
            'last_lat': w.get('last_lat'),
            'last_lng': w.get('last_lng'),
            'active_issues': active_issues_count
        })
        
    # 4. Active routes
    routes = list(db.routes.find({
        'community_id': ObjectId(community_id),
        'status': 'active'
    }))
    active_routes = []
    for r in routes:
        worker = db.users.find_one({'_id': r['worker_id']})
        active_routes.append({
            'route_id': str(r['_id']),
            'worker_name': worker['name'] if worker else 'Unknown Worker',
            'issue_count': len(r.get('issue_ids', [])),
            'total_distance_km': r.get('total_distance_km', 0.0),
            'created_at': r.get('created_at').isoformat()
        })
        
    # 5. Urgent unassigned
    urgent_unassigned = db.issues.count_documents({
        'community_id': ObjectId(community_id),
        'severity': {'$gte': 4},
        'status': 'validated',
        'assigned_to': None
    })
    
    base_data['pending_users_count'] = pending_users_count
    base_data['active_workers'] = active_workers
    base_data['active_routes'] = active_routes
    base_data['urgent_unassigned'] = urgent_unassigned
    
    # Municipal recommendations advisor
    recommendations = clustering_service.generate_municipal_recommendations(community_id)
    base_data['recommendations'] = recommendations
    
    return jsonify({
        'success': True,
        'message': 'Authority dashboard statistics retrieved',
        'data': base_data
    }), 200

@dashboard_bp.route('/hotspots/<community_id>', methods=['GET'])
@require_auth
def community_hotspots(community_id):
    hotspots = clustering_service.get_community_hotspots(community_id)
    return jsonify({
        'success': True,
        'message': 'Hotspots retrieved',
        'data': hotspots
    }), 200

@dashboard_bp.route('/export/<community_id>', methods=['GET'])
@require_role('authority')
def export_dashboard(community_id):
    date_from_str = request.args.get('date_from')
    date_to_str = request.args.get('date_to')
    
    query = {'community_id': ObjectId(community_id)}
    
    # Filter issues by date range if provided
    date_filter = {}
    if date_from_str:
        try:
            date_filter['$gte'] = datetime.fromisoformat(date_from_str)
        except ValueError:
            pass
    if date_to_str:
        try:
            date_filter['$lte'] = datetime.fromisoformat(date_to_str)
        except ValueError:
            pass
            
    if date_filter:
        query['created_at'] = date_filter
        
    issues = list(db.issues.find(query).sort([('created_at', -1)]))
    
    # Enrich issues
    for iss in issues:
        if iss.get('is_anonymous'):
            iss['reporter_name'] = "Anonymous Resident"
        else:
            rep = db.users.find_one({'_id': iss.get('reporter_id')})
            iss['reporter_name'] = rep['name'] if rep else "Unknown Resident"
            
    community = db.communities.find_one({'_id': ObjectId(community_id)})
    
    export_data = {
        'community_name': community['name'] if community else 'Unknown',
        'city': community['city'] if community else '',
        'state': community['state'] if community else '',
        'export_time': datetime.utcnow().isoformat(),
        'date_from': date_from_str,
        'date_to': date_to_str,
        'total_count': len(issues),
        'resolved_count': sum(1 for i in issues if i['status'] == 'resolved'),
        'open_count': sum(1 for i in issues if i['status'] in ['pending_validation', 'validated', 'assigned', 'in_progress']),
        'issues': serialize(issues)
    }
    
    return jsonify({
        'success': True,
        'message': 'Export dataset ready',
        'data': export_data
    }), 200
