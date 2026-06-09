from datetime import datetime, timedelta

SLA_DAYS = {
    'water': 1,
    'sewage': 1,
    'garbage': 2,
    'streetlight': 3,
    'noise': 5,
    'pothole': 7,
    'other': 7
}

def get_sla_deadline(category: str, created_at: datetime) -> datetime:
    days = SLA_DAYS.get(category, 7)
    return created_at + timedelta(days=days)

def get_sla_status(issue: dict) -> dict:
    deadline = issue.get('sla_deadline')
    created_at = issue.get('created_at')
    category = issue.get('category', 'other')
    
    if isinstance(deadline, str):
        try:
            deadline = datetime.fromisoformat(deadline.replace('Z', '+00:00')).replace(tzinfo=None)
        except Exception:
            deadline = None
            
    if isinstance(created_at, str):
        try:
            created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00')).replace(tzinfo=None)
        except Exception:
            created_at = None
            
    now = datetime.utcnow()
    
    if not deadline:
        return {
            'deadline_iso': None,
            'days_remaining': None,
            'is_overdue': False,
            'percent_elapsed': 0.0,
            'sla_days': SLA_DAYS.get(category, 7)
        }
        
    days_remaining = (deadline - now).days
    # If same day, check hours or fallback
    if days_remaining == 0:
        # Check hours remaining
        hours = (deadline - now).total_seconds() / 3600
        days_remaining = round(hours / 24.0, 2)
        
    is_overdue = now > deadline
    
    percent_elapsed = 0.0
    if created_at:
        total_sec = (deadline - created_at).total_seconds()
        if total_sec > 0:
            elapsed_sec = (now - created_at).total_seconds()
            percent_elapsed = min(100.0, max(0.0, (elapsed_sec / total_sec) * 100))
            
    return {
        'deadline_iso': deadline.isoformat(),
        'days_remaining': days_remaining,
        'is_overdue': is_overdue,
        'percent_elapsed': round(percent_elapsed, 1),
        'sla_days': SLA_DAYS.get(category, 7)
    }

def check_and_flag_sla_breaches():
    from app import db
    from services.score_service import apply_score_change
    from services.notification_service import notify_authority_room
    
    now = datetime.utcnow()
    # Find all unresolved (not in 'resolved', 'rejected') issues where deadline has passed and sla_breached is False
    unresolved_statuses = ['pending_validation', 'validated', 'assigned', 'in_progress']
    breached_issues = list(db.issues.find({
        'status': {'$in': unresolved_statuses},
        'sla_deadline': {'$lt': now},
        'sla_breached': {'$ne': True}
    }))
    
    for issue in breached_issues:
        db.issues.update_one(
            {'_id': issue['_id']},
            {'$set': {'sla_breached': True}}
        )
        apply_score_change(str(issue['community_id']), -3, f"SLA breached: {issue['title']}")
        
        # Notify authority room via SocketIO
        data = {
            'issue_id': str(issue['_id']),
            'title': issue['title'],
            'category': issue['category'],
            'severity': issue.get('severity', 3)
        }
        notify_authority_room(str(issue['community_id']), 'sla_breach', data)
