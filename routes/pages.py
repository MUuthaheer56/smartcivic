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




