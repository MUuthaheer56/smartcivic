from flask import Blueprint, render_template

pages_bp = Blueprint('pages', __name__)

@pages_bp.route('/')
def index():
    return render_template('index.html')

@pages_bp.route('/login')
def login():
    return render_template('login.html')

@pages_bp.route('/register')
def register():
    return render_template('register.html')

@pages_bp.route('/report')
def report_issue():
    return render_template('report_issue.html')

@pages_bp.route('/issues')
def issue_list():
    return render_template('issue_list.html')

@pages_bp.route('/issues/<issue_id>')
def issue_detail(issue_id):
    return render_template('issue_detail.html', issue_id=issue_id)

@pages_bp.route('/my-issues')
def my_issues():
    return render_template('my_issues.html')

@pages_bp.route('/community')
def community_dashboard():
    return render_template('community_dashboard.html')

@pages_bp.route('/authority')
def authority_dashboard():
    return render_template('authority_dashboard.html')

@pages_bp.route('/worker')
def worker_view():
    return render_template('worker_view.html')

@pages_bp.route('/worker/stats')
def worker_stats():
    return render_template('worker_stats.html')

@pages_bp.route('/onboarding')
def onboarding_tour():
    return render_template('onboarding_tour.html')

@pages_bp.route('/api/notifications/', methods=['GET'])
def get_user_notifications():
    from flask import g
    from bson import ObjectId
    from app import db
    from utils import serialize
    from services.auth_service import require_auth
    
    # We apply require_auth dynamically since require_auth is a decorator
    @require_auth
    def _get():
        notifs = list(db.notifications.find({'user_id': ObjectId(g.user['user_id'])}).sort([('created_at', -1)]))
        return {
            'success': True,
            'message': 'Notifications retrieved',
            'data': serialize(notifs)
        }
    return _get()

@pages_bp.route('/api/notifications/<notif_id>/read', methods=['PUT'])
def read_notification(notif_id):
    from flask import g
    from bson import ObjectId
    from app import db
    from services.auth_service import require_auth
    
    @require_auth
    def _read():
        db.notifications.update_one(
            {'_id': ObjectId(notif_id), 'user_id': ObjectId(g.user['user_id'])},
            {'$set': {'is_read': True}}
        )
        return {
            'success': True,
            'message': 'Notification marked as read',
            'data': None
        }
    return _read()


