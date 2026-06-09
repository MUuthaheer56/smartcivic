from datetime import datetime
from bson import ObjectId
from statistics import mean

CONFIRM_THRESHOLD = 3
DENY_THRESHOLD = 3
MIN_VOTES_FOR_REJECT = 5

def check_and_validate(issue_id: str):
    from app import db
    import services.sla_service as sla_service
    from services.score_service import apply_score_change
    from services.reputation_service import award_reputation
    from services.notification_service import notify_user, notify_community_room, notify_authority_room
    
    issue = db.issues.find_one({'_id': ObjectId(issue_id)})
    if not issue:
        return
        
    if issue.get('status') != 'pending_validation':
        return
        
    confirm = issue.get('confirm_votes', 0)
    deny = issue.get('deny_votes', 0)
    total = confirm + deny
    severity_votes = issue.get('severity_votes', [])
    community_id = str(issue['community_id'])
    reporter_id = str(issue['reporter_id'])
    title = issue['title']
    now = datetime.utcnow()
    
    # 1. Validation path
    if confirm >= CONFIRM_THRESHOLD and confirm > deny:
        severity = round(mean(severity_votes)) if severity_votes else 3
        sla_deadline = sla_service.get_sla_deadline(issue['category'], issue.get('created_at', now))
        
        db.issues.update_one(
            {'_id': ObjectId(issue_id)},
            {
                '$set': {
                    'status': 'validated',
                    'severity': severity,
                    'validated_at': now,
                    'sla_deadline': sla_deadline
                },
                '$push': {
                    'status_history': {
                        'status': 'validated',
                        'changed_by': None,
                        'timestamp': now,
                        'note': 'Validated by community votes.'
                    }
                }
            }
        )
        
        # Adjust community score
        apply_score_change(community_id, +1, 'Issue validated')
        
        # Award reputation to reporter
        award_reputation(reporter_id, +5, 'Issue validated by community')
        
        # Award reputation to confirm voters
        voters = list(db.votes.find({'issue_id': ObjectId(issue_id), 'vote_type': 'confirm'}))
        for vote in voters:
            award_reputation(str(vote['voter_id']), +2, 'Voted with majority (confirm)')
            
        # Notify reporter
        notify_user(
            user_id=reporter_id,
            message=f"Your issue '{title}' was validated! SLA deadline: {sla_deadline.date()}.",
            notif_type="issue_validated",
            issue_id=issue_id
        )
        
        # Notify community room
        comm_data = {
            'issue_id': str(issue_id),
            'title': title,
            'severity': severity,
            'category': issue['category']
        }
        notify_community_room(community_id, 'issue_validated', comm_data)
        
        # Notify authority room if urgent
        if severity >= 4:
            auth_data = {
                'issue_id': str(issue_id),
                'title': title,
                'severity': severity,
                'lat': issue['lat'],
                'lng': issue['lng'],
                'category': issue['category']
            }
            notify_authority_room(community_id, 'urgent_issue', auth_data)
            
    # 2. Rejection path
    elif deny >= DENY_THRESHOLD and deny > confirm and total >= MIN_VOTES_FOR_REJECT:
        db.issues.update_one(
            {'_id': ObjectId(issue_id)},
            {
                '$set': {
                    'status': 'rejected'
                },
                '$push': {
                    'status_history': {
                        'status': 'rejected',
                        'changed_by': None,
                        'timestamp': now,
                        'note': 'Rejected by community votes.'
                    }
                }
            }
        )
        
        # Adjust community score
        apply_score_change(community_id, +1, 'False issue rejected')
        
        # Award reputation to deny voters
        voters = list(db.votes.find({'issue_id': ObjectId(issue_id), 'vote_type': 'deny'}))
        for vote in voters:
            award_reputation(str(vote['voter_id']), +2, 'Voted with majority (deny)')
            
        # Notify reporter
        notify_user(
            user_id=reporter_id,
            message=f"Your issue '{title}' was rejected by community vote.",
            notif_type="issue_rejected",
            issue_id=issue_id
        )
