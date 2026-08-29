from flask import Blueprint, render_template, g
from services.auth_service import require_role

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

@pages_bp.route('/ai-insights')
def ai_insights():
    return render_template('ai_insights.html')

@pages_bp.route('/api/admin/ward-report', methods=['GET'])
@require_role('authority')
def admin_ward_report_route():
    from flask import request, jsonify, g
    from app import db
    from services.ward_report_service import generate_ward_monthly_report
    
    ward = request.args.get("ward")
    month = request.args.get("month")
    year = request.args.get("year")
    
    if not ward or not month or not year:
        return jsonify({"success": False, "message": "Missing ward, month, or year"}), 400
        
    try:
        month = int(month)
        year = int(year)
    except ValueError:
        return jsonify({"success": False, "message": "Invalid month or year"}), 400
        
    report = generate_ward_monthly_report(ward, month, year, db)
    return jsonify({"success": True, "data": report}), 200




