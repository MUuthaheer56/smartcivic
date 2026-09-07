"""
SmartCivic+ — Main entry point
Starts the web server using native threading async mode.
"""
import sys
import os

from app import create_app, socketio, start_background_jobs

app = create_app()

if __name__ == '__main__':
    import sys
    import os
    os.makedirs("logs", exist_ok=True)
    os.makedirs("static/uploads/issues", exist_ok=True)
    scheduler = start_background_jobs(app)
    print("==================================================", flush=True)
    print(" [*] SmartCivic+ Development Web Server Started", flush=True)
    print(" [*] Listening on: http://127.0.0.1:5000", flush=True)
    print(" [*] JSON Logs:    logs/smartcivic.log", flush=True)
    print(" [*] Press Ctrl+C to terminate the server", flush=True)
    print("==================================================", flush=True)
    sys.stdout.flush()
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, allow_unsafe_werkzeug=True)
