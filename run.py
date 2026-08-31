"""
SmartCivic+ — Main entry point
Starts the eventlet WSGI web server.
"""
import eventlet
eventlet.monkey_patch()

from app import create_app, socketio

app = create_app()

if __name__ == '__main__':
    import sys
    print("==================================================", flush=True)
    print(" [*] SmartCivic+ Development Web Server Started", flush=True)
    print(" [*] Listening on: http://127.0.0.1:5000", flush=True)
    print(" [*] JSON Logs:    logs/smartcivic.log", flush=True)
    print(" [*] Press Ctrl+C to terminate the server", flush=True)
    print("==================================================", flush=True)
    sys.stdout.flush()
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)
