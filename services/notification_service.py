from datetime import datetime, timedelta
from bson import ObjectId
from flask import current_app
from flask_mail import Message

def notify_user(user_id, message, notif_type, issue_id=None):
    from app import db, socketio
    
    # Write to DB
    notif_doc = {
        "user_id": ObjectId(user_id),
        "message": message,
        "type": notif_type,
        "issue_id": ObjectId(issue_id) if issue_id else None,
        "is_read": False,
        "created_at": datetime.utcnow()
    }
    db.notifications.insert_one(notif_doc)
    
    # Emit socket event
    from utils import serialize
    socketio.emit(
        'notification', 
        serialize(notif_doc), 
        room=f"user_{user_id}", 
        namespace='/civic'
    )

def notify_community_room(community_id, event, data):
    from app import socketio
    from utils import serialize
    socketio.emit(event, serialize(data), room=f"community_{community_id}", namespace='/civic')

def notify_authority_room(community_id, event, data):
    from app import socketio
    from utils import serialize
    socketio.emit(event, serialize(data), room=f"authority_{community_id}", namespace='/civic')

def notify_worker_room(worker_id, event, data):
    from app import socketio
    from utils import serialize
    socketio.emit(event, serialize(data), room=f"worker_{worker_id}", namespace='/civic')

def send_email(to, subject, html_body):
    from app import mail
    try:
        msg = Message(
            subject=subject,
            recipients=[to],
            html=html_body
        )
        mail.send(msg)
        return True
    except Exception as e:
        print(f"Error sending email to {to}: {e}")
        return False

def send_weekly_digest(community_id):
    from app import db
    community = db.communities.find_one({'_id': ObjectId(community_id)})
    if not community:
        return
        
    score = community.get('community_score', 100)
    resolved_count = community.get('resolved_issues', 0)
    open_count = community.get('open_issues', 0)
    
    # Top unresolved issue by severity
    top_issue = db.issues.find_one(
        {
            'community_id': ObjectId(community_id),
            'status': {'$in': ['validated', 'assigned', 'in_progress']}
        },
        sort=[('severity', -1), ('created_at', 1)]
    )
    
    top_issue_title = top_issue['title'] if top_issue else "No urgent unresolved issues!"
    top_issue_severity = top_issue.get('severity', 1) if top_issue else 0
    
    # Fetch residents
    residents = list(db.users.find({'community_id': ObjectId(community_id), 'role': 'resident'}))
    
    for resident in residents:
        email = resident.get('email')
        if not email:
            continue
            
        html_body = f"""
        <html>
            <body style="font-family: Arial, sans-serif; color: #333;">
                <div style="background-color: #2563EB; color: white; padding: 20px; text-align: center;">
                    <h1>SmartCivic Weekly Digest</h1>
                    <p style="font-size: 1.2em; font-weight: bold;">{community['name']} Community Status</p>
                </div>
                <div style="padding: 20px; border: 1px solid #ddd; border-top: none;">
                    <h3>Community Performance Indicators:</h3>
                    <ul>
                        <li><strong>Community Maintenance Score:</strong> {score}/100</li>
                        <li><strong>Issues Resolved:</strong> {resolved_count}</li>
                        <li><strong>Issues Still Open:</strong> {open_count}</li>
                    </ul>
                    <hr/>
                    <h3>Top Unresolved Priority:</h3>
                    <p>"{top_issue_title}" (Severity: {'★' * top_issue_severity})</p>
                    <hr/>
                    <p>Keep your community clean and active! Report new issues or cast votes on open reports by logging into SmartCivic.</p>
                    <div style="text-align: center; margin-top: 20px;">
                        <a href="{current_app.config.get('APP_BASE_URL', 'http://localhost:5000') + '/community'}" style="background-color: #2563EB; color: white; padding: 10px 20px; text-decoration: none; border-radius: 4px; font-weight: bold;">Go to Dashboard</a>
                    </div>
                </div>
            </body>
        </html>
        """
        send_email(to=email, subject=f"SmartCivic Weekly Digest: {community['name']}", html_body=html_body)
