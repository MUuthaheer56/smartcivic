import os
from flask import Flask, jsonify
from flask_socketio import SocketIO
from flask_mail import Mail
from pymongo import MongoClient
from config import Config

socketio = SocketIO()
mail = Mail()
db = None

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'docs'), exist_ok=True)
    
    socketio.init_app(app, cors_allowed_origins='*', async_mode='eventlet')
    mail.init_app(app)
    
    global db
    client = MongoClient(app.config['MONGO_URI'])
    db = client[app.config['DB_NAME']]
    


    import routes.sockets  # registers Socket.IO event handlers
    
    # MongoDB Indexes
    db.users.create_index('email', unique=True)
    db.issues.create_index([('lat', 1), ('lng', 1)])
    db.issues.create_index('community_id')
    db.issues.create_index('status')
    db.issues.create_index([('title', 'text'), ('description', 'text'), ('address', 'text')])
    db.votes.create_index([('issue_id', 1), ('voter_id', 1)], unique=True)
    db.notifications.create_index([('user_id', 1), ('is_read', 1)])
    db.announcements.create_index('community_id')
    db.login_attempts.create_index("ip", expireAfterSeconds=900)
    db.notifications.create_index([("user_id", 1), ("delivery_status", 1)])
    db.audit_logs.create_index([("user_id", 1), ("timestamp", -1)])
    db.issues.create_index("suppressed")
    
    # Rate limiter state (in-memory, per IP, per minute)
    app.rate_limit_store = {}
    
    # Blueprints
    from routes.auth import auth_bp
    from routes.issues import issues_bp
    from routes.votes import votes_bp
    from routes.communities import communities_bp
    from routes.workers import workers_bp
    from routes.dashboard import dashboard_bp
    from routes.announcements import announcements_bp
    from routes.pages import pages_bp
    
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(issues_bp, url_prefix='/api/issues')
    app.register_blueprint(votes_bp, url_prefix='/api/votes')
    app.register_blueprint(communities_bp, url_prefix='/api/communities')
    app.register_blueprint(workers_bp, url_prefix='/api/workers')
    app.register_blueprint(dashboard_bp, url_prefix='/api/dashboard')
    app.register_blueprint(announcements_bp, url_prefix='/api/announcements')
    app.register_blueprint(pages_bp)
    from routes.notifications import notifications_bp
    app.register_blueprint(notifications_bp, url_prefix='/api/notifications')
    
    from routes.ai_routes import ai_bp
    from routes.issues import complaints_bp
    app.register_blueprint(ai_bp, url_prefix='/api/ai')
    app.register_blueprint(complaints_bp, url_prefix='/api/complaints')
    
    # Start background scheduler (do not run in testing)
    if not app.config.get('TESTING') and os.environ.get('WERKZEUG_RUN_MAIN') != 'false':
        from services.scheduler_service import start_scheduler
        start_scheduler(app)
    
    # Error handlers
    @app.errorhandler(400)
    def e400(e): return jsonify({'success': False, 'message': 'Bad request', 'data': None}), 400
    @app.errorhandler(401)
    def e401(e): return jsonify({'success': False, 'message': 'Unauthorized', 'data': None}), 401
    @app.errorhandler(403)
    def e403(e): return jsonify({'success': False, 'message': 'Forbidden', 'data': None}), 403
    @app.errorhandler(404)
    def e404(e): return jsonify({'success': False, 'message': 'Not found', 'data': None}), 404
    @app.errorhandler(500)
    def e500(e): return jsonify({'success': False, 'message': 'Server error', 'data': None}), 500
    
    return app
