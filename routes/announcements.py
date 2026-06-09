from datetime import datetime
from flask import Blueprint, request, jsonify, g
from bson import ObjectId
from app import db
from utils import serialize
from services.auth_service import require_role
from services.notification_service import notify_community_room

announcements_bp = Blueprint('announcements', __name__)

@announcements_bp.route('/', methods=['POST'])
@require_role('authority')
def create_announcement():
    data = request.get_json() or {}
    title = data.get('title')
    body = data.get('body')
    expires_at = data.get('expires_at')
    
    if not title or not body:
        return jsonify({'success': False, 'message': 'Missing title or body', 'data': None}), 400
        
    expires_dt = None
    if expires_at:
        try:
            expires_dt = datetime.fromisoformat(expires_at.replace('Z', '+00:00')).replace(tzinfo=None)
        except ValueError:
            return jsonify({'success': False, 'message': 'Invalid expiry date ISO format', 'data': None}), 400
            
    community_id = ObjectId(g.user['community_id'])
    
    ann_doc = {
        'title': title.strip(),
        'body': body.strip(),
        'community_id': community_id,
        'created_by': ObjectId(g.user['user_id']),
        'created_at': datetime.utcnow(),
        'expires_at': expires_dt,
        'is_active': True
    }
    
    inserted_id = db.announcements.insert_one(ann_doc).inserted_id
    
    # Notify community room via Socket
    socket_data = {
        'announcement_id': str(inserted_id),
        'title': title,
        'body': body
    }
    notify_community_room(str(community_id), 'new_announcement', socket_data)
    
    return jsonify({
        'success': True,
        'message': 'Announcement created successfully',
        'data': {
            'announcement_id': str(inserted_id)
        }
    }), 201

@announcements_bp.route('/<community_id>', methods=['GET'])
def get_announcements(community_id):
    now = datetime.utcnow()
    query = {
        'community_id': ObjectId(community_id),
        'is_active': True,
        '$or': [
            {'expires_at': None},
            {'expires_at': {'$gt': now}}
        ]
    }
    
    announcements = list(db.announcements.find(query).sort([('created_at', -1)]))
    return jsonify({
        'success': True,
        'message': 'Announcements retrieved',
        'data': serialize(announcements)
    }), 200

@announcements_bp.route('/<announcement_id>', methods=['DELETE'])
@require_role('authority')
def delete_announcement(announcement_id):
    announcement = db.announcements.find_one({'_id': ObjectId(announcement_id)})
    if not announcement:
        return jsonify({'success': False, 'message': 'Announcement not found', 'data': None}), 404
        
    # Verify authority is in the same community
    if str(announcement['community_id']) != g.user['community_id']:
        return jsonify({'success': False, 'message': 'Unauthorized: Announcement is from a different community', 'data': None}), 403
        
    db.announcements.update_one(
        {'_id': ObjectId(announcement_id)},
        {'$set': {'is_active': False}}
    )
    
    return jsonify({'success': True, 'message': 'Announcement deleted successfully', 'data': None}), 200
