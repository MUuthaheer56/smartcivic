from datetime import datetime
from flask import Blueprint, request, jsonify, g
from bson import ObjectId
from app import db
from services.auth_service import require_auth, require_verified
import services.validation_service as validation_service

votes_bp = Blueprint('votes', __name__)

@votes_bp.route('/cast', methods=['POST'])
@require_verified
def cast_vote():
    data = request.get_json() or {}
    issue_id = data.get('issue_id')
    vote_type = data.get('vote_type') # "confirm" or "deny"
    severity_vote = data.get('severity_vote') # 1-5
    
    if not all([issue_id, vote_type, severity_vote]):
        return jsonify({'success': False, 'message': 'Missing required fields', 'data': None}), 400
        
    if vote_type not in ['confirm', 'deny']:
        return jsonify({'success': False, 'message': 'Invalid vote type', 'data': None}), 400
        
    try:
        severity_vote = int(severity_vote)
        if not (1 <= severity_vote <= 5):
            raise ValueError()
    except ValueError:
        return jsonify({'success': False, 'message': 'Severity vote must be an integer between 1 and 5', 'data': None}), 400
        
    issue = db.issues.find_one({'_id': ObjectId(issue_id)})
    if not issue:
        return jsonify({'success': False, 'message': 'Issue not found', 'data': None}), 404
        
    if issue.get('status') != 'pending_validation':
        return jsonify({'success': False, 'message': 'Issue is not in pending_validation status', 'data': None}), 400
        
    voter_id = ObjectId(g.user['user_id'])
    if issue.get('reporter_id') == voter_id:
        return jsonify({'success': False, 'message': 'You cannot vote on your own reported issue', 'data': None}), 400
        
    # Check duplicate vote
    existing = db.votes.find_one({'issue_id': ObjectId(issue_id), 'voter_id': voter_id})
    if existing:
        return jsonify({'success': False, 'message': 'You have already voted on this issue', 'data': None}), 400
        
    # Insert vote
    vote_doc = {
        'issue_id': ObjectId(issue_id),
        'voter_id': voter_id,
        'vote_type': vote_type,
        'severity_vote': severity_vote,
        'timestamp': datetime.utcnow()
    }
    
    try:
        db.votes.insert_one(vote_doc)
    except Exception:
        # DB unique index safety
        return jsonify({'success': False, 'message': 'You have already voted on this issue', 'data': None}), 400
        
    # Update issue counts
    inc_field = 'confirm_votes' if vote_type == 'confirm' else 'deny_votes'
    db.issues.update_one(
        {'_id': ObjectId(issue_id)},
        {
            '$inc': {inc_field: 1},
            '$push': {'severity_votes': severity_vote}
        }
    )
    
    # Increment user vote count
    db.users.update_one({'_id': voter_id}, {'$inc': {'votes_count': 1}})
    
    # Run validation checks
    validation_service.check_and_validate(issue_id)
    
    updated_issue = db.issues.find_one({'_id': ObjectId(issue_id)})
    return jsonify({
        'success': True,
        'message': 'Vote cast successfully!',
        'data': {
            'confirm_votes': updated_issue.get('confirm_votes', 0),
            'deny_votes': updated_issue.get('deny_votes', 0)
        }
    }), 201

@votes_bp.route('/issue/<issue_id>', methods=['GET'])
@require_auth
def get_issue_votes(issue_id):
    issue = db.issues.find_one({'_id': ObjectId(issue_id)})
    if not issue:
        return jsonify({'success': False, 'message': 'Issue not found', 'data': None}), 404
        
    votes = list(db.votes.find({'issue_id': ObjectId(issue_id)}))
    
    confirm_count = sum(1 for v in votes if v['vote_type'] == 'confirm')
    deny_count = sum(1 for v in votes if v['vote_type'] == 'deny')
    
    distribution = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    for v in votes:
        sev = v.get('severity_vote')
        if sev in distribution:
            distribution[sev] += 1
            
    # Check if this user voted
    user_vote = db.votes.find_one({'issue_id': ObjectId(issue_id), 'voter_id': ObjectId(g.user['user_id'])})
    user_has_voted = user_vote is not None
    user_vote_type = user_vote['vote_type'] if user_vote else None
    
    return jsonify({
        'success': True,
        'message': 'Vote stats retrieved',
        'data': {
            'confirm_count': confirm_count,
            'deny_count': deny_count,
            'total': len(votes),
            'severity_distribution': distribution,
            'user_has_voted': user_has_voted,
            'user_vote_type': user_vote_type
        }
    }), 200
