import os
import uuid
import re
from datetime import datetime
from flask import Blueprint, request, jsonify, g, current_app
from bson import ObjectId
from app import db
from utils import serialize
from services.auth_service import (
    hash_password, check_password, create_token, 
    rate_limit, require_auth, require_role
)
from services.notification_service import send_email

auth_bp = Blueprint('auth', __name__)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS']

@auth_bp.route('/register', methods=['POST'])
@rate_limit(10)
def register():
    # Multipart form-data
    name = request.form.get('name')
    email = request.form.get('email')
    password = request.form.get('password')
    confirm_password = request.form.get('confirm_password')
    role = request.form.get('role')
    community_id = request.form.get('community_id')
    verification_doc = request.files.get('verification_doc')
    
    # Validation
    if not all([name, email, password, confirm_password, role, community_id]):
        return jsonify({'success': False, 'message': 'Missing required fields', 'data': None}), 400
        
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        return jsonify({'success': False, 'message': 'Invalid email format', 'data': None}), 400
        
    if password != confirm_password:
        return jsonify({'success': False, 'message': 'Passwords do not match', 'data': None}), 400
        
    if len(password) < 6:
        return jsonify({'success': False, 'message': 'Password must be at least 6 characters long', 'data': None}), 400
        
    if role not in ['resident', 'field_worker']:
        return jsonify({'success': False, 'message': 'Invalid role choice. Authorities cannot self-register.', 'data': None}), 400
        
    # Check email uniqueness
    if db.users.find_one({'email': email.lower()}):
        return jsonify({'success': False, 'message': 'Email already registered', 'data': None}), 400
        
    # Process verification document
    doc_path = None
    if verification_doc:
        if not allowed_file(verification_doc.filename):
            return jsonify({'success': False, 'message': 'Invalid file extension', 'data': None}), 400
            
        ext = verification_doc.filename.rsplit('.', 1)[1].lower()
        filename = f"{uuid.uuid4()}.{ext}"
        save_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'docs')
        doc_path = os.path.join('static', 'uploads', 'docs', filename).replace('\\', '/')
        verification_doc.save(os.path.join(save_dir, filename))
        
    # Hash password and insert user
    pwd_hash = hash_password(password)
    user_doc = {
        "name": name.strip(),
        "email": email.lower().strip(),
        "password_hash": pwd_hash,
        "role": role,
        "community_id": ObjectId(community_id),
        "is_verified": False,
        "verification_doc": doc_path,
        "created_at": datetime.utcnow(),
        "last_login": datetime.utcnow(),
        "reports_count": 0,
        "votes_count": 0,
        "issues_resolved_count": 0,
        "reputation_score": 0,
        "reputation_tier": "Newcomer",
        "is_anonymous_by_default": False,
        "last_lat": None,
        "last_lng": None,
        "onboarding_complete": False,
        "preferred_language": "en"
    }
    
    db.users.insert_one(user_doc)
    return jsonify({'success': True, 'message': 'Registration successful! Pending verification.', 'data': None}), 201

@auth_bp.route('/login', methods=['POST'])
@rate_limit(20)
def login():
    data = request.get_json() or {}
    email = data.get('email')
    password = data.get('password')
    
    if not email or not password:
        return jsonify({'success': False, 'message': 'Missing email or password', 'data': None}), 400
        
    ip = request.remote_addr or "unknown"
    from services.auth_service import rate_limit_login_by_ip, record_failed_attempt, clear_login_attempts, audit_log_action
    
    allowed, rem = rate_limit_login_by_ip(ip, db)
    if not allowed:
        return jsonify({'success': False, 'message': 'Too many attempts. Try again in 15 min.', 'data': None}), 429
        
    user = db.users.find_one({'email': email.lower().strip()})
    if not user or not check_password(password, user['password_hash']):
        record_failed_attempt(ip, db)
        return jsonify({'success': False, 'message': 'Invalid email or password', 'data': None}), 401
        
    if not user.get('is_verified', False):
        return jsonify({'success': False, 'message': 'Account pending verification by authority', 'data': None}), 403
        
    # Clear on success
    clear_login_attempts(ip, db)
    
    # Audit log
    audit_log_action(str(user['_id']), "LOGIN", {"email": email.lower().strip()}, db)
        
    # Update last login
    now = datetime.utcnow()
    db.users.update_one({'_id': user['_id']}, {'$set': {'last_login': now}})
    
    token = create_token(
        user_id=user['_id'],
        role=user['role'],
        community_id=user.get('community_id')
    )
    
    user_info = {
        'user_id': str(user['_id']),
        'name': user['name'],
        'role': user['role'],
        'community_id': str(user['community_id']) if user.get('community_id') else None,
        'reputation_score': user.get('reputation_score', 0),
        'reputation_tier': user.get('reputation_tier', 'Newcomer'),
        'onboarding_complete': user.get('onboarding_complete', False),
        'preferred_language': user.get('preferred_language', 'en')
    }
    
    return jsonify({
        'success': True,
        'message': 'Login successful',
        'data': {
            'token': token,
            'user': user_info
        }
    }), 200

@auth_bp.route('/me', methods=['GET'])
@require_auth
def me():
    user = db.users.find_one({'_id': ObjectId(g.user['user_id'])})
    if not user:
        return jsonify({'success': False, 'message': 'User not found', 'data': None}), 404
        
    return jsonify({
        'success': True,
        'message': 'Profile retrieved',
        'data': serialize(user)
    }), 200

@auth_bp.route('/profile', methods=['PUT'])
@require_auth
def profile():
    data = request.get_json() or {}
    preferred_language = data.get('preferred_language')
    is_anonymous_by_default = data.get('is_anonymous_by_default')
    
    update_data = {}
    if preferred_language in ['en', 'hi', 'kn']:
        update_data['preferred_language'] = preferred_language
    if is_anonymous_by_default is not None:
        update_data['is_anonymous_by_default'] = bool(is_anonymous_by_default)
        
    if not update_data:
        return jsonify({'success': False, 'message': 'No profile fields provided to update', 'data': None}), 400
        
    db.users.update_one({'_id': ObjectId(g.user['user_id'])}, {'$set': update_data})
    
    updated_user = db.users.find_one({'_id': ObjectId(g.user['user_id'])})
    return jsonify({
        'success': True,
        'message': 'Profile updated successfully',
        'data': serialize(updated_user)
    }), 200

@auth_bp.route('/onboarding-complete', methods=['PUT'])
@require_auth
def onboarding_complete():
    db.users.update_one({'_id': ObjectId(g.user['user_id'])}, {'$set': {'onboarding_complete': True}})
    return jsonify({'success': True, 'message': 'Onboarding marked complete', 'data': None}), 200

@auth_bp.route('/pending-users', methods=['GET'])
@require_role('authority')
def pending_users():
    community_id = ObjectId(g.user['community_id'])
    users = list(db.users.find({
        'community_id': community_id,
        'is_verified': False
    }))
    return jsonify({
        'success': True,
        'message': 'Pending verification user list',
        'data': serialize(users)
    }), 200

@auth_bp.route('/verify-user/<user_id>', methods=['PUT'])
@require_role('authority')
def verify_user(user_id):
    # Verify the user belongs to the same community
    user = db.users.find_one({'_id': ObjectId(user_id)})
    if not user:
        return jsonify({'success': False, 'message': 'User not found', 'data': None}), 404
        
    if str(user.get('community_id')) != g.user['community_id']:
        return jsonify({'success': False, 'message': 'Unauthorized: User is not in your community', 'data': None}), 403
        
    db.users.update_one({'_id': ObjectId(user_id)}, {'$set': {'is_verified': True}})
    
    # Send email notification
    send_email(
        to=user['email'],
        subject="Your SmartCivic account has been approved!",
        html_body=f"Hi {user['name']},<br/><br/>Your account on SmartCivic has been verified by the community authority! You can now log in and report/vote on issues.<br/><br/>Thanks,<br/>SmartCivic Team"
    )
    
    return jsonify({'success': True, 'message': 'User account verified successfully', 'data': None}), 200

@auth_bp.route('/reject-user/<user_id>', methods=['DELETE'])
@require_role('authority')
def reject_user(user_id):
    user = db.users.find_one({'_id': ObjectId(user_id)})
    if not user:
        return jsonify({'success': False, 'message': 'User not found', 'data': None}), 404
        
    if str(user.get('community_id')) != g.user['community_id']:
        return jsonify({'success': False, 'message': 'Unauthorized: User is not in your community', 'data': None}), 403
        
    # Delete doc
    db.users.delete_one({'_id': ObjectId(user_id)})
    
    # Optional document cleanup
    if user.get('verification_doc'):
        try:
            os.remove(user['verification_doc'])
        except Exception:
            pass
            
    return jsonify({'success': True, 'message': 'User account application rejected and deleted', 'data': None}), 200

@auth_bp.route('/all-residents', methods=['GET'])
@require_role('authority')
def all_residents():
    community_id = ObjectId(g.user['community_id'])
    
    is_verified_param = request.args.get('is_verified')
    search_query = request.args.get('search', '').strip()
    
    query = {
        'community_id': community_id,
        'role': 'resident'
    }
    
    if is_verified_param == 'true':
        query['is_verified'] = True
    elif is_verified_param == 'false':
        query['is_verified'] = False
        
    if search_query:
        query['$or'] = [
            {'name': {'$regex': search_query, '$options': 'i'}},
            {'email': {'$regex': search_query, '$options': 'i'}}
        ]
        
    residents = list(db.users.find(query).sort([('created_at', -1)]))
    return jsonify({
        'success': True,
        'message': 'Residents list retrieved successfully',
        'data': serialize(residents)
    }), 200

@auth_bp.route('/revoke-user/<user_id>', methods=['PUT'])
@require_role('authority')
def revoke_user(user_id):
    user = db.users.find_one({'_id': ObjectId(user_id)})
    if not user:
        return jsonify({'success': False, 'message': 'User not found', 'data': None}), 404
        
    if str(user.get('community_id')) != g.user['community_id']:
        return jsonify({'success': False, 'message': 'Unauthorized: User is not in your community', 'data': None}), 403
        
    db.users.update_one({'_id': ObjectId(user_id)}, {'$set': {'is_verified': False}})
    
    # Send email notification
    send_email(
        to=user['email'],
        subject="Your SmartCivic account verification has been revoked",
        html_body=f"Hi {user['name']},<br/><br/>Your account verification on SmartCivic has been revoked by the community authority. Please contact your local authority if you believe this is an error.<br/><br/>Thanks,<br/>SmartCivic Team"
    )
    
    return jsonify({'success': True, 'message': 'User account verification revoked successfully', 'data': None}), 200

