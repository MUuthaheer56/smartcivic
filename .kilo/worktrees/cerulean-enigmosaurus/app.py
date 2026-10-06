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

# Connect to MongoDB at module level for thread safety and easy service imports.
# Use the Config.MONGO_CLIENT_KWARGS hardened defaults — see config.py comments
# for the rationale (timeouts, pool size, majority writes, journaling, …).
# Operators can still override any individual value via the MONGO_URI query
# string (e.g. ?maxPoolSize=50) because URI parameters take precedence.
mongo_uri = Config.MONGO_URI
_client_kwargs = dict(getattr(Config, "MONGO_CLIENT_KWARGS", {}))
# Allow explicit override for dev: if MONGO_URI is still localhost-default and
# no user/password was embedded, skip "authSource=admin" to keep local dev UX
# simple.  For production, scripts/harden_mongo.py generates URIs with
# user:pass@host embedded + authSource query params already.
client = MongoClient(mongo_uri, **_client_kwargs)
from pymongo.uri_parser import parse_uri

def get_db_name(uri):
    try:
        parsed = parse_uri(uri)
        return parsed.get("database") or "smartcivic"
    except Exception:
        return "smartcivic"

db_name = get_db_name(mongo_uri)
db = client[db_name]

try:
    from flask_wtf.csrf import CSRFProtect
    csrf = CSRFProtect()
except ImportError:
    class DummyCSRF:
        def init_app(self, app): pass
        def exempt(self, bp): pass
    csrf = DummyCSRF()

# Initialize Socket.IO and Limiter
socketio = SocketIO(cors_allowed_origins="*", async_mode="threading")
limiter = Limiter(key_func=get_remote_address, default_limits=["200 per hour"], storage_uri="memory://")


def _validate_runtime_config(config_cls) -> None:
    SECRET_KEY = getattr(config_cls, "SECRET_KEY", None)
    JWT_SECRET = getattr(config_cls, "JWT_SECRET", None)
    MONGO_URI = getattr(config_cls, "MONGO_URI", None)
    FLASK_ENV = os.getenv("FLASK_ENV", os.getenv("ENV", "development")).lower()

    if not SECRET_KEY or not SECRET_KEY.strip() or "replace_" in SECRET_KEY.lower():
        raise RuntimeError(
            "CRITICAL: SECRET_KEY is not configured securely. Set a strong random "
            "value (e.g. `openssl rand -hex 32`) in your .env file before starting."
        )
    if not JWT_SECRET or not JWT_SECRET.strip() or "replace_" in JWT_SECRET.lower():
        raise RuntimeError(
            "CRITICAL: JWT_SECRET is not configured securely. Set a strong random "
            "value different from SECRET_KEY in your .env file before starting."
        )
    if SECRET_KEY == JWT_SECRET:
        raise RuntimeError(
            "CRITICAL: SECRET_KEY and JWT_SECRET MUST be different random values. "
            "Using the same secret for CSRF/session and JWT signing is unsafe."
        )
    if FLASK_ENV in ("production", "prod"):
        if not MONGO_URI or "localhost" in MONGO_URI or "127.0.0.1" in MONGO_URI:
            raise RuntimeError(
                "CRITICAL: Production mode detected but MONGO_URI points to localhost. "
                "Configure a secure, remote MongoDB connection string before deploying."
            )
        # Production: MONGO_URI must carry credentials (user:password userinfo).
        # If there's no userinfo, MongoDB will fall back to the localhost auth
        # bypass, which means we effectively have no authentication.
        from urllib.parse import urlparse
        try:
            parsed = urlparse(MONGO_URI)
        except Exception as exc:
            raise RuntimeError(f"CRITICAL: MONGO_URI is malformed: {exc}") from None
        if not parsed.username or not parsed.password:
            raise RuntimeError(
                "CRITICAL: Production MONGO_URI has no embedded credentials "
                "(username:password).  Use `python scripts/harden_mongo.py bootstrap` "
                "to create least-privilege users and a URI with authSource/SCRAM."
            )
        if not parsed.scheme == "mongodb" and not parsed.scheme == "mongodb+srv":
            raise RuntimeError(
                "CRITICAL: Production MONGO_URI must use mongodb:// or mongodb+srv:// scheme."
            )
        # TLS is required in production — either scheme is mongodb+srv (implies
        # TLS) or the URI carries tls=true / ssl=true in its query string.
        query_lower = (parsed.query or "").lower()
        tls_on = (parsed.scheme == "mongodb+srv"
                  or "tls=true" in query_lower
                  or "ssl=true" in query_lower)
        if not tls_on:
            raise RuntimeError(
                "CRITICAL: Production MongoDB connections must use TLS.  Either "
                "switch to a mongodb+srv:// Atlas-style URI or append "
                "'&tls=true&tlsAllowInvalidCertificates=false' to MONGO_URI."
            )
        COOKIE_SECURE = getattr(config_cls, "COOKIE_SECURE", False)
        if not COOKIE_SECURE:
            raise RuntimeError(
                "CRITICAL: Production mode requires COOKIE_SECURE=true. Set it in "
                "your .env to ensure JWT cookies are only sent over HTTPS."
            )

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    _validate_runtime_config(Config)
    app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
    
    # Initialize extensions with app context
    socketio.init_app(app)
    limiter.init_app(app)
    csrf.init_app(app)

    
    # Initialize background SLA escalation scheduler
    try:
        from services.sla_escalation import run_escalation_check
        scheduler = BackgroundScheduler(daemon=True)
        scheduler.add_job(run_escalation_check, 'interval', minutes=30)
        scheduler.start()
    except Exception as e:
        print(f"[APScheduler] Warning starting background SLA scheduler: {e}")
    
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
    app.register_blueprint(auth_bp, url_prefix='/api/auth', name='api_auth')
    app.register_blueprint(citizen_bp)
    app.register_blueprint(officer_bp)
    app.register_blueprint(worker_bp)
    
    # Register REST API blueprints
    from routes.api.issues import issues_api_bp
    from routes.api.workers import workers_api_bp
    from routes.api.analytics import analytics_api_bp
    from routes.api.map import map_api_bp
    from routes.api.auth_mobile import api_mobile_auth_bp
    
    app.register_blueprint(issues_api_bp)
    app.register_blueprint(workers_api_bp)
    app.register_blueprint(analytics_api_bp)
    app.register_blueprint(map_api_bp)
    app.register_blueprint(api_mobile_auth_bp)
    
    from routes.api.simulation import simulation_api_bp
    from routes.api.civicpulse import civicpulse_api_bp
    app.register_blueprint(simulation_api_bp)
    app.register_blueprint(civicpulse_api_bp)

    from routes.api.notifications import notifications_api_bp
    from routes.api.graph import graph_bp
    app.register_blueprint(notifications_api_bp)
    app.register_blueprint(graph_bp)

    from routes.location import location_bp
    app.register_blueprint(location_bp)

    # Exempt REST API blueprints using Bearer token authentication from form CSRF checks
    csrf.exempt(issues_api_bp)
    csrf.exempt(workers_api_bp)
    csrf.exempt(analytics_api_bp)
    csrf.exempt(map_api_bp)
    csrf.exempt(simulation_api_bp)
    csrf.exempt(civicpulse_api_bp)
    csrf.exempt(graph_bp)
    csrf.exempt(notifications_api_bp)
    csrf.exempt(auth_bp)
    csrf.exempt(api_mobile_auth_bp)
    csrf.exempt(location_bp)

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

    @app.route('/map')
    def live_map_page():
        return render_template('public/live_map.html')
        
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
        
        trusted_cdns = (
            "https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://unpkg.com "
            "https://fonts.googleapis.com https://fonts.gstatic.com https://raw.githubusercontent.com "
            "https://*.openstreetmap.org https://*.tile.openstreetmap.org https://tile.openstreetmap.org "
            "http://router.project-osrm.org https://router.project-osrm.org https://nominatim.openstreetmap.org"
        )
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
        from werkzeug.exceptions import HTTPException
        if isinstance(e, HTTPException):
            if request.path.startswith("/api/"):
                return jsonify({
                    "success": False,
                    "error": {
                        "code": e.name.upper().replace(" ", "_"),
                        "message": e.description or str(e)
                    }
                }), e.code
            return render_template("error.html", message=e.description or str(e)), e.code

        app.logger.error(f"Server error: {e}", exc_info=True)
        # Return JSON only for API routes; render a plain error page for browser routes
        if request.path.startswith("/api/"):
            return jsonify({
                "success": False,
                "error": {
                    "code": "SERVER_ERROR",
                    "message": "An internal server error occurred."
                }
            }), 500
        return render_template("error.html",
                               message="An unexpected error occurred. Please try again."), 500

    @app.errorhandler(404)
    def not_found(e):
        if request.path.startswith('/api/'):
            return jsonify({"success": False, "error": {"code": "NOT_FOUND", "message": "Endpoint not found"}}), 404
        return render_template('errors/404.html'), 404

    # Index creation is safe to repeat; data seeding stays an explicit operator action.
    try:
        from setup_indexes import create_indexes
        create_indexes()
    except Exception as e:
        app.logger.warning(f"Startup index setup skipped: {e}")


    return app


def start_background_jobs(app):
    """Starts APScheduler background jobs outside create_app factory."""
    scheduler = BackgroundScheduler()

    def sla_sweep_job():
        with app.app_context():
            open_issues = list(db.issues.find({"status": {"$nin": ["closed", "rejected"]}}))
            from services.sla_service import check_sla_status
            for issue in open_issues:
                try:
                    check_sla_status(issue)
                except Exception as sweep_err:
                    app.logger.error(f"SLA Sweep error on issue {issue.get('_id')}: {sweep_err}")

    scheduler.add_job(sla_sweep_job, 'interval', seconds=app.config.get("SLA_CHECK_INTERVAL", 900))

    def briefing_and_health_job():
        with app.app_context():
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
        with app.app_context():
            try:
                from services.prediction_service import compute_hotspots
                compute_hotspots()
            except Exception as err:
                app.logger.error(f"Weekly predictive hotspot computation exception: {err}")

    scheduler.add_job(prediction_hotspots_job, 'cron', day_of_week='sun', hour=1)

    def infrastructure_health_sweep_job():
        with app.app_context():
            try:
                from services.infrastructure_service import trigger_all_infrastructure_recalc
                trigger_all_infrastructure_recalc()
            except Exception as err:
                app.logger.error(f"Infrastructure Health sweep exception: {err}")

    scheduler.add_job(infrastructure_health_sweep_job, 'interval', hours=6)

    def weekly_intelligence_report_job():
        with app.app_context():
            try:
                from services.report_service import trigger_report_generation_job
                trigger_report_generation_job()
            except Exception as err:
                app.logger.error(f"Weekly Intelligence Report generation exception: {err}")

    scheduler.add_job(weekly_intelligence_report_job, 'cron', day_of_week='mon', hour=6)

    def daily_database_backup_job():
        with app.app_context():
            try:
                from scripts.backup_db import run_backup
                run_backup()
            except Exception as err:
                app.logger.error(f"Daily Database Backup sweep exception: {err}")

    scheduler.add_job(daily_database_backup_job, 'cron', hour=2, minute=0)

    def civicpulse_prediction_job():
        with app.app_context():
            try:
                from services.civicpulse_service import compute_civicpulse_predictions
                compute_civicpulse_predictions()
            except Exception as err:
                app.logger.error(f"CivicPulse prediction sweep exception: {err}")

    scheduler.add_job(civicpulse_prediction_job, 'cron', day_of_week='tue', hour=2)

    if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not app.debug:
        scheduler.start()
    return scheduler

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
        secret = current_app.config["JWT_SECRET"]
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
