"""
SmartCivic+ — Main Entry Point
================================

Dual-mode launcher:
  * Development (default): Flask/Werkzeug built-in server + Socket.IO `run()`
    on http://127.0.0.1:5000 — NEVER expose this directly to the internet.
  * Production (pass --prod or set SMARTCIVIC_PROD=1):
        Linux/macOS -> Prints a helpful pointer to the Gunicorn invocation via
                       `wsgi.py` (see Procfile / Dockerfile for the canonical
                       command).  Gunicorn does not run on Windows.
        Windows     -> Starts `waitress-serve` programmatically against wsgi:app
                       so operators can run a production-grade server without
                       WSL or Docker.  Requires `pip install waitress`.

Background jobs (SLA checks, AI briefings, CivicPulse, backups) are started by
both the dev launcher and the `wsgi.py` production entry point — the exact same
APScheduler configuration runs in either case.
"""
import os
import sys
import argparse
import platform

from app import create_app, socketio, start_background_jobs, db

app = create_app()


def print_startup_dashboard(is_production: bool, server: str, bind: str):
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
    print(f" [SERVER]     {server} ({'PRODUCTION' if is_production else 'DEVELOPMENT'} mode)", flush=True)
    print(" [AUTH]       Use configured accounts or register as a citizen", flush=True)
    print(" [STAFF AUTH] Admin invite code is required and never uses a default", flush=True)
    print(" --------------------------------------------------------------------------", flush=True)
    print(f" [*] Server Running at: http://{bind}", flush=True)
    print(" [*] Application Logs:  logs/smartcivic.log", flush=True)
    print(" [*] Press Ctrl+C to stop the server", flush=True)
    print("==========================================================================\n", flush=True)


def _run_dev(host: str, port: int):
    """Werkzeug / Socket.IO dev server — NEVER use this on a public network."""
    os.makedirs("logs", exist_ok=True)
    os.makedirs("static/uploads/issues", exist_ok=True)
    scheduler = start_background_jobs(app)
    print_startup_dashboard(False,
                            server="Flask/Werkzeug + Socket.IO (DEV)",
                            bind=f"{host}:{port}")
    socketio.run(app, host=host, port=port, debug=False,
                 allow_unsafe_werkzeug=True)


def _print_gunicorn_help(port: int):
    """Linux/macOS production launcher: print the canonical Gunicorn command."""
    print("", flush=True)
    print("==========================================================================", flush=True)
    print("  SMARTCIVIC+ PRODUCTION LAUNCH (Linux / macOS)                           ", flush=True)
    print("==========================================================================", flush=True)
    print("  --prod was requested, but the built-in Flask dev server MUST NOT be", flush=True)
    print("  exposed to production traffic.  Launch via Gunicorn against `wsgi:app`:", flush=True)
    print("")
    print("    gunicorn \\")
    print(f"        --workers ${{GUNICORN_WORKERS:-1}} \\")
    print(f"        --threads ${{GUNICORN_THREADS:-32}} \\")
    print(f"        --timeout ${{GUNICORN_TIMEOUT:-120}} \\")
    print(f"        --bind 0.0.0.0:{port} \\")
    print("        --forwarded-allow-ips='*' \\")
    print("        --access-logfile - --error-logfile - \\")
    print("        --capture-output \\")
    print("        wsgi:app")
    print("")
    print("  See Procfile, Dockerfile, and wsgi.py for the authoritative recipe.", flush=True)
    print("  To force-start the DEV server anyway, re-run without --prod.", flush=True)
    print("==========================================================================", flush=True)
    sys.exit(0)


def _run_waitress(host: str, port: int):
    """Waitress — pure-Python production server (Windows-safe, no eventlet)."""
    try:
        from waitress import serve
    except ImportError:
        print("", flush=True)
        print("======================================================================", flush=True)
        print("  PRODUCTION MODE ABORTED: Waitress is not installed.", flush=True)
        print("  Install it with:  pip install waitress", flush=True)
        print("  Then re-run:      python run.py --prod", flush=True)
        print("  Or use Docker (Dockerfile builds with Gunicorn for all platforms).", flush=True)
        print("======================================================================", flush=True)
        sys.exit(2)

    os.makedirs("logs", exist_ok=True)
    os.makedirs("static/uploads/issues", exist_ok=True)
    # Import wsgi so the scheduler and app are constructed exactly once.
    import wsgi as wsgi_mod
    print_startup_dashboard(True,
                            server="Waitress (PRODUCTION — pure-Python)",
                            bind=f"{host}:{port}")
    serve(wsgi_mod.app, host=host, port=port, threads=32,
          connection_limit=256, channel_timeout=120)


def main():
    parser = argparse.ArgumentParser(description="SmartCivic+ launcher (dev or prod).")
    parser.add_argument("--host", default="0.0.0.0",
                        help="Bind address (default: 0.0.0.0 for all interfaces).")
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("PORT", "5000")),
                        help="Listen port (default: $PORT or 5000).")
    parser.add_argument("--prod", action="store_true",
                        help=("Launch a production server.  On Windows this uses "
                              "Waitress; on Linux/macOS this prints the Gunicorn "
                              "command (Gunicorn is the supported way) instead of "
                              "accidentally launching Werkzeug into production."))
    args = parser.parse_args()

    production = args.prod or (os.environ.get("SMARTCIVIC_PROD", "").strip()
                                 .lower() in ("1", "true", "yes", "on"))

    if not production:
        _run_dev(args.host, args.port)
        return

    # Production path
    if platform.system().lower() == "windows":
        _run_waitress(args.host, args.port)
    else:
        _print_gunicorn_help(args.port)


if __name__ == '__main__':
    main()
