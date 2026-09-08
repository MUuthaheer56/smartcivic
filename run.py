"""
SmartCivic+ — Main entry point
Starts the web server using native threading async mode with full startup health dashboard.
"""
import sys
import os

from app import create_app, socketio, start_background_jobs, db

app = create_app()

def print_startup_dashboard():
    print("\n==========================================================================", flush=True)
    print("                    SMARTCIVIC+ SYSTEM STARTUP                            ", flush=True)
    print("==========================================================================", flush=True)
    
    # 1. Database Status
    try:
        db.command('ping')
        issue_count = db.issues.count_documents({})
        user_count = db.users.count_documents({})
        print(f" [DB STATUS]  MongoDB Connected | {user_count} Users | {issue_count} Complaints Registered", flush=True)
    except Exception as err:
        print(f" [DB STATUS]  MongoDB Warning: {err}", flush=True)
        
    # 2. Registered Blueprints & Features
    print(" [FEATURES]   Auth, Citizen Portal, Worker Ops, Officer Command, GIS Maps", flush=True)
    print(" [AI ENGINE]  Gemini API + Rule-based NLP Triage & Vision Fallback", flush=True)
    print(" [SECURITY]   JWT Cookies (HttpOnly), RBAC Enforcement, CSP Headers", flush=True)
    
    # 3. Deployment guidance
    print(" --------------------------------------------------------------------------", flush=True)
    print(" [AUTH]       Use configured accounts or register as a citizen", flush=True)
    print(" [STAFF AUTH] Admin invite code is required and never uses a default", flush=True)
    print(" --------------------------------------------------------------------------", flush=True)
    print(" [*] Server Running at: http://127.0.0.1:5000", flush=True)
    print(" [*] Application Logs:  logs/smartcivic.log", flush=True)
    print(" [*] Press Ctrl+C to stop the server", flush=True)
    print("==========================================================================\n", flush=True)

if __name__ == '__main__':
    os.makedirs("logs", exist_ok=True)
    os.makedirs("static/uploads/issues", exist_ok=True)
    scheduler = start_background_jobs(app)
    print_startup_dashboard()
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, allow_unsafe_werkzeug=True)
