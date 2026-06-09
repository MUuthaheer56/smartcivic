from datetime import datetime, timedelta
from bson import ObjectId

SCORE_RULES = {
    'new_issue': -2,
    'issue_validated': +1,
    'issue_rejected': +1,
    'issue_resolved': +5,
    'stale_7days': -3,
    'stale_severe_3days': -5
}

def apply_score_change(community_id: str, change: int, reason: str):
    from app import db
    community = db.communities.find_one({'_id': ObjectId(community_id)})
    if not community:
        return
        
    current = community.get('community_score', 100)
    new_score = max(0, min(100, current + change))
    now = datetime.utcnow()
    
    db.communities.update_one(
        {'_id': ObjectId(community_id)},
        {
            '$set': {'community_score': new_score},
            '$push': {
                'score_history': {
                    '$each': [{
                        'score': new_score,
                        'change': change,
                        'reason': reason,
                        'timestamp': now
                    }],
                    '$slice': -30
                }
            }
        }
    )
    print(f"Score change: community {community_id} {change:+d} ({reason}) \u2192 {new_score}")

def check_stale_issues():
    from app import db
    now = datetime.utcnow()
    
    # 1. status='validated', validated_at < now-7days, and stale_7days_applied not true
    cutoff_7d = now - timedelta(days=7)
    stale_issues_7d = list(db.issues.find({
        'status': 'validated',
        'validated_at': {'$lt': cutoff_7d},
        'stale_7days_applied': {'$ne': True}
    }))
    
    for issue in stale_issues_7d:
        db.issues.update_one(
            {'_id': issue['_id']},
            {'$set': {'stale_7days_applied': True}}
        )
        apply_score_change(issue['community_id'], SCORE_RULES['stale_7days'], f"Issue stale for 7 days: {issue['title']}")
        
    # 2. status in [validated, assigned, in_progress], severity >= 4, created_at < now-3days, and stale_3days_applied not true
    cutoff_3d = now - timedelta(days=3)
    stale_issues_3d = list(db.issues.find({
        'status': {'$in': ['validated', 'assigned', 'in_progress']},
        'severity': {'$gte': 4},
        'created_at': {'$lt': cutoff_3d},
        'stale_3days_applied': {'$ne': True}
    }))
    
    for issue in stale_issues_3d:
        db.issues.update_one(
            {'_id': issue['_id']},
            {'$set': {'stale_3days_applied': True}}
        )
        apply_score_change(issue['community_id'], SCORE_RULES['stale_severe_3days'], f"Severe issue stale for 3 days: {issue['title']}")
