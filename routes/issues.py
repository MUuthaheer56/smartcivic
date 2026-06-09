import os
import uuid
from datetime import datetime
from flask import Blueprint, request, jsonify, g, current_app
from bson import ObjectId
from app import db
from utils import serialize
from PIL import Image
from services.auth_service import require_auth, require_role, require_verified, rate_limit
import services.sla_service as sla_service
import services.score_service as score_service
import services.reputation_service as reputation_service
from services.notification_service import (
    notify_user, notify_community_room, notify_authority_room
)
from services.route_optimizer import haversine

issues_bp = Blueprint('issues', __name__)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS']

@issues_bp.route('/report', methods=['POST'])
@require_verified
@rate_limit(5)
def report_issue():
    title = request.form.get('title')
    description = request.form.get('description')
    category = request.form.get('category')
    lat = request.form.get('lat')
    lng = request.form.get('lng')
    address = request.form.get('address')
    is_anonymous_str = request.form.get('is_anonymous', 'false')
    is_anonymous = is_anonymous_str.lower() == 'true'
    
    linked_issue_id = request.form.get('linked_issue_id')
    linked_ids = []
    if linked_issue_id and linked_issue_id.strip():
        try:
            linked_ids.append(ObjectId(linked_issue_id.strip()))
        except Exception:
            pass
            
    if not all([title, description, category, lat, lng, address]):
        return jsonify({'success': False, 'message': 'Missing required fields', 'data': None}), 400
        
    try:
        lat = float(lat)
        lng = float(lng)
    except ValueError:
        return jsonify({'success': False, 'message': 'Invalid coordinates', 'data': None}), 400
        
    community_id = ObjectId(g.user['community_id'])
    reporter_id = ObjectId(g.user['user_id'])
    
    # Handle image uploads
    images_files = request.files.getlist('images[]')
    saved_images = []
    
    # Create community folder in uploads
    comm_upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], str(community_id))
    os.makedirs(comm_upload_dir, exist_ok=True)
    
    for img_file in images_files[:3]: # Limit to max 3
        if img_file and allowed_file(img_file.filename):
            try:
                filename = f"{uuid.uuid4()}.jpg"
                filepath = os.path.join(comm_upload_dir, filename)
                
                # Resize and convert to RGB/JPEG using Pillow
                image = Image.open(img_file)
                if image.mode != 'RGB':
                    image = image.convert('RGB')
                    
                if image.width > 1200:
                    w_percent = (1200 / float(image.width))
                    h_size = int((float(image.height) * float(w_percent)))
                    image = image.resize((1200, h_size), Image.Resampling.LANCZOS)
                    
                image.save(filepath, 'JPEG')
                saved_images.append(f"static/uploads/{community_id}/{filename}")
            except Exception as e:
                print(f"Error processing image: {e}")
                
    # Check for nearby duplicates within 200m (0.2 km)
    nearby_issue = None
    existing_issues = list(db.issues.find({
        'community_id': community_id,
        'category': category,
        'status': {'$ne': 'rejected'}
    }))
    
    for old_issue in existing_issues:
        dist = haversine(lat, lng, old_issue['lat'], old_issue['lng'])
        if dist <= 0.2: # 200 meters
            nearby_issue = {
                'issue_id': str(old_issue['_id']),
                'title': old_issue['title']
            }
            # Return duplicate warning if client did not bypass it
            bypass = request.form.get('bypass_duplicate', 'false').lower() == 'true'
            if not bypass:
                return jsonify({
                    'success': True,
                    'message': 'Potential duplicate issue detected nearby.',
                    'data': {
                        'nearby_duplicate': nearby_issue
                    }
                }), 200
                
    # Insert new issue
    now = datetime.utcnow()
    deadline = sla_service.get_sla_deadline(category, now)
    
    issue_doc = {
        "title": title.strip(),
        "description": description.strip(),
        "category": category,
        "images": saved_images,
        "lat": lat,
        "lng": lng,
        "address": address.strip(),
        "community_id": community_id,
        "reporter_id": reporter_id,
        "is_anonymous": is_anonymous,
        "status": "pending_validation",
        "severity": 3,
        "severity_override": None,
        "severity_override_by": None,
        "confirm_votes": 0,
        "deny_votes": 0,
        "severity_votes": [],
        "upvotes": 0,
        "upvoted_by": [],
        "linked_issue_ids": linked_ids,
        "validated_at": None,
        "assigned_to": None,
        "assigned_at": None,
        "resolved_at": None,
        "resolution_note": None,
        "resolution_image": None,
        "created_at": now,
        "sla_deadline": deadline,
        "sla_breached": False,
        "comments": [],
        "status_history": [
            {
                "status": "pending_validation",
                "changed_by": reporter_id,
                "timestamp": now,
                "note": "Issue reported."
            }
        ]
    }
    
    inserted_id = db.issues.insert_one(issue_doc).inserted_id
    
    if linked_ids:
        try:
            db.issues.update_one(
                {'_id': linked_ids[0]},
                {'$push': {'linked_issue_ids': inserted_id}}
            )
        except Exception as e:
            print(f"Error linking parent issue: {e}")
            
    # Update community statistics
    db.communities.update_one(
        {'_id': community_id},
        {'$inc': {'open_issues': 1, 'total_issues': 1}}
    )
    
    # Score change
    score_service.apply_score_change(str(community_id), -2, 'New issue reported')
    
    # Update user stats
    db.users.update_one({'_id': reporter_id}, {'$inc': {'reports_count': 1}})
    
    # Notify 5 most active residents
    active_users = list(db.users.find(
        {
            'community_id': community_id,
            'role': 'resident',
            '_id': {'$ne': reporter_id}
        },
        sort=[('votes_count', -1)],
        limit=5
    ))
    
    for active_u in active_users:
        notify_user(
            user_id=str(active_u['_id']),
            message=f"New issue reported in your area: '{title}'. Please vote to validate.",
            notif_type="vote_request",
            issue_id=str(inserted_id)
        )
        
    # Socket broadcast
    notify_community_room(
        community_id=str(community_id),
        event='new_issue',
        data={'issue_id': str(inserted_id), 'title': title, 'category': category}
    )
    
    return jsonify({
        'success': True,
        'message': 'Issue reported successfully!',
        'data': {
            'issue_id': str(inserted_id)
        }
    }), 201

@issues_bp.route('/', methods=['GET'])
@require_auth
def list_issues():
    comm_id = request.args.get('community_id')
    if not comm_id:
        return jsonify({'success': False, 'message': 'Missing community_id query parameter', 'data': None}), 400
        
    status = request.args.get('status')
    category = request.args.get('category')
    min_severity = request.args.get('min_severity')
    search = request.args.get('search')
    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 10))
    
    query = {'community_id': ObjectId(comm_id)}
    if status:
        query['status'] = status
    if category:
        query['category'] = category
    if min_severity:
        try:
            query['severity'] = {'$gte': int(min_severity)}
        except ValueError:
            pass
            
    if search:
        query['$or'] = [
            {'title': {'$regex': search, '$options': 'i'}},
            {'description': {'$regex': search, '$options': 'i'}},
            {'address': {'$regex': search, '$options': 'i'}}
        ]
        
    total = db.issues.count_documents(query)
    issues = list(db.issues.find(query).sort([('created_at', -1)]).skip((page-1)*limit).limit(limit))
    
    # Enrich issues
    for issue in issues:
        # Check anonymous
        if issue.get('is_anonymous'):
            issue['reporter_name'] = "Anonymous Resident"
        else:
            reporter = db.users.find_one({'_id': issue.get('reporter_id')})
            issue['reporter_name'] = reporter['name'] if reporter else "Unknown Resident"
            
        # SLA status
        issue['sla_status'] = sla_service.get_sla_status(issue)
        
    return jsonify({
        'success': True,
        'message': 'Issues retrieved',
        'data': {
            'issues': serialize(issues),
            'total': total,
            'page': page,
            'limit': limit
        }
    }), 200

@issues_bp.route('/<issue_id>', methods=['GET'])
def get_issue(issue_id):
    issue = db.issues.find_one({'_id': ObjectId(issue_id)})
    if not issue:
        return jsonify({'success': False, 'message': 'Issue not found', 'data': None}), 404
        
    # Enrich reporter details
    if issue.get('is_anonymous'):
        issue['reporter_name'] = "Anonymous Resident"
    else:
        reporter = db.users.find_one({'_id': issue.get('reporter_id')})
        issue['reporter_name'] = reporter['name'] if reporter else "Unknown Resident"
        
    # SLA status
    issue['sla_status'] = sla_service.get_sla_status(issue)
    
    # Votes summary
    issue['vote_summary'] = {
        'confirm_votes': issue.get('confirm_votes', 0),
        'deny_votes': issue.get('deny_votes', 0),
        'total_votes': issue.get('confirm_votes', 0) + issue.get('deny_votes', 0)
    }
    
    # Worker name
    worker_name = None
    if issue.get('assigned_to'):
        worker = db.users.find_one({'_id': ObjectId(issue['assigned_to'])})
        if worker:
            worker_name = worker['name']
    issue['assigned_worker_name'] = worker_name
    
    return jsonify({
        'success': True,
        'message': 'Issue retrieved successfully',
        'data': serialize(issue)
    }), 200

@issues_bp.route('/<issue_id>/upvote', methods=['POST'])
@require_verified
def upvote_issue(issue_id):
    user_id = ObjectId(g.user['user_id'])
    
    issue = db.issues.find_one({'_id': ObjectId(issue_id)})
    if not issue:
        return jsonify({'success': False, 'message': 'Issue not found', 'data': None}), 404
        
    if user_id in issue.get('upvoted_by', []):
        return jsonify({'success': False, 'message': 'You have already upvoted this issue', 'data': None}), 400
        
    db.issues.update_one(
        {'_id': ObjectId(issue_id)},
        {
            '$inc': {'upvotes': 1},
            '$push': {'upvoted_by': user_id}
        }
    )
    
    updated = db.issues.find_one({'_id': ObjectId(issue_id)}, {'upvotes': 1})
    return jsonify({
        'success': True,
        'message': 'Upvoted successfully',
        'data': {
            'upvotes': updated.get('upvotes', 0)
        }
    }), 200

@issues_bp.route('/<issue_id>/comment', methods=['POST'])
@require_verified
def comment_issue(issue_id):
    data = request.get_json() or {}
    text = data.get('text', '').strip()
    
    if len(text) < 3 or len(text) > 500:
        return jsonify({'success': False, 'message': 'Comment must be between 3 and 500 characters', 'data': None}), 400
        
    user_id = ObjectId(g.user['user_id'])
    name = g.user['name']
    
    issue = db.issues.find_one({'_id': ObjectId(issue_id)})
    if not issue:
        return jsonify({'success': False, 'message': 'Issue not found', 'data': None}), 404
        
    # Anonymity override: check if the commenter wants to be anonymous or if defaults apply
    commenter_name = "Anonymous" if g.user.get('is_anonymous_by_default') else name
    
    comment = {
        'user_id': user_id,
        'name': commenter_name,
        'text': text,
        'timestamp': datetime.utcnow()
    }
    
    db.issues.update_one(
        {'_id': ObjectId(issue_id)},
        {'$push': {'comments': comment}}
    )
    
    # Award reputation
    reputation_service.award_reputation(str(user_id), +1, 'Comment posted')
    
    updated_issue = db.issues.find_one({'_id': ObjectId(issue_id)}, {'comments': 1})
    return jsonify({
        'success': True,
        'message': 'Comment added successfully',
        'data': serialize(updated_issue.get('comments', []))
    }), 200

@issues_bp.route('/<issue_id>/status', methods=['PUT'])
@require_role('authority', 'field_worker')
def update_status(issue_id):
    # Form data or JSON
    status = request.form.get('status') or request.json.get('status') if request.is_json else request.form.get('status')
    note = request.form.get('note') or request.json.get('note') if request.is_json else request.form.get('note')
    resolution_image = request.files.get('resolution_image') if 'resolution_image' in request.files else None
    
    if not status:
        return jsonify({'success': False, 'message': 'Status field is required', 'data': None}), 400
        
    issue = db.issues.find_one({'_id': ObjectId(issue_id)})
    if not issue:
        return jsonify({'success': False, 'message': 'Issue not found', 'data': None}), 404
        
    now = datetime.utcnow()
    update_fields = {'status': status}
    
    if status == 'resolved':
        update_fields['resolved_at'] = now
        update_fields['resolution_note'] = note
        
        # Save resolution image
        if resolution_image and allowed_file(resolution_image.filename):
            try:
                filename = f"resolution_{uuid.uuid4()}.jpg"
                save_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], str(issue['community_id']))
                os.makedirs(save_dir, exist_ok=True)
                filepath = os.path.join(save_dir, filename)
                
                image = Image.open(resolution_image)
                if image.mode != 'RGB':
                    image = image.convert('RGB')
                    
                if image.width > 1200:
                    w_percent = (1200 / float(image.width))
                    h_size = int((float(image.height) * float(w_percent)))
                    image = image.resize((1200, h_size), Image.Resampling.LANCZOS)
                    
                image.save(filepath, 'JPEG')
                update_fields['resolution_image'] = f"static/uploads/{issue['community_id']}/{filename}"
            except Exception as e:
                print(f"Error saving resolution image: {e}")
                
        # Scoring & Reputation changes
        score_service.apply_score_change(str(issue['community_id']), +5, 'Issue resolved')
        reputation_service.award_reputation(str(issue['reporter_id']), +10, 'Issue resolved')
        
        # Increments Resolved Counts
        db.communities.update_one(
            {'_id': issue['community_id']},
            {'$inc': {'resolved_issues': 1, 'open_issues': -1}}
        )
        
        # Notify reporter
        notify_user(
            user_id=str(issue['reporter_id']),
            message=f"Your reported issue '{issue['title']}' has been resolved!",
            notif_type="issue_resolved",
            issue_id=issue_id
        )
        
    elif status == 'in_progress':
        # Check if SLA breached and mark if true
        deadline = issue.get('sla_deadline')
        if deadline and now > deadline and not issue.get('sla_breached', False):
            update_fields['sla_breached'] = True
            score_service.apply_score_change(str(issue['community_id']), -3, 'SLA breached')
            
    db.issues.update_one(
        {'_id': ObjectId(issue_id)},
        {
            '$set': update_fields,
            '$push': {
                'status_history': {
                    'status': status,
                    'changed_by': ObjectId(g.user['user_id']),
                    'timestamp': now,
                    'note': note or f"Status updated to {status}."
                }
            }
        }
    )
    
    # Broadcast status change
    notify_community_room(
        community_id=str(issue['community_id']),
        event='issue_updated',
        data={'issue_id': issue_id, 'status': status, 'note': note}
    )
    
    return jsonify({'success': True, 'message': 'Status updated successfully', 'data': None}), 200

@issues_bp.route('/<issue_id>/severity-override', methods=['PUT'])
@require_role('authority')
def severity_override(issue_id):
    data = request.get_json() or {}
    severity = data.get('severity')
    
    if severity is None or not (1 <= int(severity) <= 5):
        return jsonify({'success': False, 'message': 'Invalid severity value. Must be 1-5.', 'data': None}), 400
        
    issue = db.issues.find_one({'_id': ObjectId(issue_id)})
    if not issue:
        return jsonify({'success': False, 'message': 'Issue not found', 'data': None}), 404
        
    original_severity = issue.get('severity', 3)
    
    db.issues.update_one(
        {'_id': ObjectId(issue_id)},
        {
            '$set': {
                'severity': int(severity),
                'severity_override': original_severity,
                'severity_override_by': ObjectId(g.user['user_id'])
            }
        }
    )
    
    updated = db.issues.find_one({'_id': ObjectId(issue_id)})
    return jsonify({
        'success': True,
        'message': 'Severity overridden successfully',
        'data': serialize(updated)
    }), 200

@issues_bp.route('/heatmap/<community_id>', methods=['GET'])
def heatmap(community_id):
    issues = list(db.issues.find(
        {
            'community_id': ObjectId(community_id),
            'status': {'$ne': 'rejected'}
        },
        {'lat': 1, 'lng': 1, 'severity': 1, 'category': 1, 'title': 1}
    ))
    return jsonify({
        'success': True,
        'message': 'Heatmap locations retrieved',
        'data': serialize(issues)
    }), 200

@issues_bp.route('/suggest-category', methods=['GET'])
def suggest_category():
    title = request.args.get('title', '').lower()
    
    keywords = {
        'water': ['water', 'pipe', 'leak', 'flood', 'drainage', 'tap'],
        'pothole': ['pothole', 'road', 'crater', 'hole', 'bump', 'damage'],
        'garbage': ['garbage', 'waste', 'trash', 'rubbish', 'dump', 'litter'],
        'streetlight': ['light', 'lamp', 'streetlight', 'dark', 'bulb', 'electric'],
        'sewage': ['sewage', 'drain', 'sewer', 'smell', 'overflow', 'stink'],
        'noise': ['noise', 'loud', 'sound', 'music', 'construction', 'barking']
    }
    
    suggested = 'other'
    for category, kw_list in keywords.items():
        if any(kw in title for kw in kw_list):
            suggested = category
            break
            
    return jsonify({
        'success': True,
        'message': 'Suggested category matching completed',
        'data': {
            'suggested_category': suggested
        }
    }), 200
