"""
SmartCivic+ — Core Application Factory
Initializes database connections, Socket.IO, security rate limiters, and background task schedulers.
"""
import os
import jwt
from datetime import datetime
from bson import ObjectId
from flask import Flask, render_template, request, redirect, g, jsonify, current_app
from pymongo import MongoClient
from flask_socketio import SocketIO, emit, join_room
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from apscheduler.schedulers.background import BackgroundScheduler

from config import Config

# Connect to MongoDB at module level for thread safety and easy service imports
mongo_uri = os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017/smartcivic")
db_name = mongo_uri.split('/')[-1] if '/' in mongo_uri else 'smartcivic'
if not db_name or db_name.strip() == "" or '?' in db_name:
    db_name = 'smartcivic'
client = MongoClient(mongo_uri)
db = client[db_name]

# Initialize Socket.IO and Limiter
socketio = SocketIO(cors_allowed_origins="*")
limiter = Limiter(key_func=get_remote_address, default_limits=["100 per minute"], storage_uri="memory://")

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    
    # Initialize extensions with app context
    socketio.init_app(app)
    limiter.init_app(app)
    
    @app.route('/api/health', methods=['GET'])
    def health_check():
        return jsonify({
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "service": "SmartCivic+"
        }), 200
    
    # Register page blueprints
    from routes.auth import auth_bp
    from routes.citizen import citizen_bp
    from routes.officer import officer_bp
    from routes.worker import worker_bp
    
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(citizen_bp)
    app.register_blueprint(officer_bp)
    app.register_blueprint(worker_bp)
    
    # Register REST API blueprints
    from routes.api.issues import issues_api_bp
    from routes.api.workers import workers_api_bp
    from routes.api.analytics import analytics_api_bp
    from routes.api.map import map_api_bp
    
    app.register_blueprint(issues_api_bp)
    app.register_blueprint(workers_api_bp)
    app.register_blueprint(analytics_api_bp)
    app.register_blueprint(map_api_bp)
    
    from routes.api.simulation import simulation_api_bp
    from routes.api.civicpulse import civicpulse_api_bp
    app.register_blueprint(simulation_api_bp)
    app.register_blueprint(civicpulse_api_bp)
    # Legacy and general page routes
    @app.route('/login')
    def login_page():
        return render_template('auth/login.html')
        
    @app.route('/register')
    def register_page():
        return render_template('auth/register.html')
        
    @app.route('/transparency')
    def transparency_page():
        return render_template('public/transparency.html')
        
    @app.route('/')
    def index():
        token = request.cookies.get("access_token")
        if token:
            try:
                payload = jwt.decode(token, app.config["JWT_SECRET"], algorithms=["HS256"])
                role = payload.get("role")
                if role == "citizen":
                    return redirect('/citizen/dashboard')
                elif role == "officer":
                    return redirect('/officer/dashboard')
                elif role == "worker":
                    return redirect('/worker/dashboard')
            except Exception:
                pass
        return redirect('/login')
        
    # Before request hook to populate g.current_user if token is valid
    @app.before_request
    def load_user_context():
        import time
        g.request_start_time = time.time()
        g.current_user = None
        token = request.cookies.get("access_token")
        if token:
            try:
                payload = jwt.decode(token, app.config["JWT_SECRET"], algorithms=["HS256"])
                user_id = payload.get("user_id")
                user = db.users.find_one({"_id": ObjectId(user_id)})
                if user:
                    g.current_user = user
            except Exception:
                pass
                
    @app.after_request
    def add_security_headers(response):
        import time
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        
        trusted_cdns = "https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://unpkg.com https://fonts.googleapis.com https://fonts.gstatic.com https://raw.githubusercontent.com https://*.openstreetmap.org"
        response.headers['Content-Security-Policy'] = (
            f"default-src 'self'; "
            f"script-src 'self' 'unsafe-inline' 'unsafe-eval' {trusted_cdns}; "
            f"style-src 'self' 'unsafe-inline' {trusted_cdns}; "
            f"img-src 'self' data: blob: {trusted_cdns}; "
            f"font-src 'self' data: {trusted_cdns}; "
            f"connect-src 'self' {trusted_cdns} ws: wss:;"
        )
        
        # Log request
        duration = 0.0
        if hasattr(g, "request_start_time"):
            duration = round((time.time() - g.request_start_time) * 1000.0, 1)
        user_id = str(g.current_user["_id"]) if (hasattr(g, "current_user") and g.current_user) else None
        
        try:
            from services.logger_service import log_api_request
            log_api_request(request.method, request.path, user_id, response.status_code, duration)
        except Exception:
            pass
            
        return response

    # Global error handlers to prevent trace leakage
    @app.errorhandler(Exception)
    def handle_exception(e):
        # Log error server-side
        app.logger.error(f"Server error: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "error": {
                "code": "SERVER_ERROR",
                "message": "An internal server error occurred."
            }
        }), 500

    # Start SLA tracking sweep scheduler (runs every 15 mins)
    scheduler = BackgroundScheduler()
    
    def sla_sweep_job():
        # Find all open issues
        open_issues = list(db.issues.find({"status": {"$nin": ["closed", "rejected"]}}))
        from services.sla_service import check_sla_status
        for issue in open_issues:
            try:
                check_sla_status(issue)
            except Exception as sweep_err:
                app.logger.error(f"SLA Sweep error on issue {issue.get('_id')}: {sweep_err}")
                
    scheduler.add_job(sla_sweep_job, 'interval', seconds=app.config["SLA_CHECK_INTERVAL"])
    
    def briefing_and_health_job():
        try:
            from services.briefing_service import regenerate_briefing, calculate_ward_health_score
            regenerate_briefing()
            wards = db.issues.distinct("ward")
            for w in wards:
                if w:
                    calculate_ward_health_score(w)
        except Exception as err:
            app.logger.error(f"Briefing & Health job background exception: {err}")
            
    scheduler.add_job(briefing_and_health_job, 'interval', minutes=30)
    
    def prediction_hotspots_job():
        try:
            from services.prediction_service import compute_hotspots
            compute_hotspots()
        except Exception as err:
            app.logger.error(f"Weekly predictive hotspot computation exception: {err}")
            
    scheduler.add_job(prediction_hotspots_job, 'cron', day_of_week='sun', hour=1)
    
    def infrastructure_health_sweep_job():
        try:
            from services.infrastructure_service import trigger_all_infrastructure_recalc
            trigger_all_infrastructure_recalc()
        except Exception as err:
            app.logger.error(f"Infrastructure Health sweep exception: {err}")
            
    scheduler.add_job(infrastructure_health_sweep_job, 'interval', hours=6)
    
    def weekly_intelligence_report_job():
        try:
            from services.report_service import trigger_report_generation_job
            trigger_report_generation_job()
        except Exception as err:
            app.logger.error(f"Weekly Intelligence Report generation exception: {err}")
            
    scheduler.add_job(weekly_intelligence_report_job, 'cron', day_of_week='mon', hour=6)
    
    def daily_database_backup_job():
        try:
            from scripts.backup_db import run_backup
            run_backup()
        except Exception as err:
            app.logger.error(f"Daily Database Backup sweep exception: {err}")
            
    scheduler.add_job(daily_database_backup_job, 'cron', hour=2, minute=0)
    
    def civicpulse_prediction_job():
        try:
            from services.civicpulse_service import compute_civicpulse_predictions
            compute_civicpulse_predictions()
        except Exception as err:
            app.logger.error(f"CivicPulse prediction sweep exception: {err}")

    # Run every Tuesday at 2am (offset from the hotspot job on Sunday)
    scheduler.add_job(civicpulse_prediction_job, 'cron', day_of_week='tue', hour=2)
    
    # Start SLA tracking sweep scheduler conditionally
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not app.debug:
        scheduler.start()
    
    return app

# Socket.IO Handlers in /civic namespace
@socketio.on('join_room', namespace='/civic')
def on_join(data):
    if not isinstance(data, dict):
        return
    room = data.get('room')
    if not room:
        return
        
    token = request.cookies.get("access_token")
    if not token:
        print("[Socket.IO] Access token cookie missing, reject join.")
        return
        
    try:
        secret = current_app.config.get("JWT_SECRET", "default_secret")
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        user_id = payload.get("user_id")
        user_role = payload.get("role")
        user_ward = payload.get("ward")
        
        # Enforce entitlements
        allowed = False
        if room == f"user_{user_id}":
            allowed = True
        elif room.startswith("ward_"):
            room_ward = room.replace("ward_", "", 1)
            # If user is officer with 'all' access or their ward matches the room's ward
            if user_role == "officer" and (user_ward == "all" or user_ward == room_ward):
                allowed = True
            elif user_ward == room_ward:
                allowed = True
        elif room == "role_officer":
            if user_role == "officer":
                allowed = True
                
        if allowed:
            join_room(room)
            print(f"[Socket.IO] Authorized join: User {user_id} joined room: {room}")
        else:
            print(f"[Socket.IO] Unauthorized join request to room: {room} by User {user_id}")
    except Exception as e:
        print(f"[Socket.IO] Join validation exception: {e}")
