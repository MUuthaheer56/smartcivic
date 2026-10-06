"""
SmartCivic+ — Production WSGI Entry Point
=========================================

This module exposes the Flask application object + background job scheduler for
production-grade WSGI servers (Gunicorn, Waitress, uWSGI).

It differs from ``run.py`` in that:
  * It does NOT call socketio.run() — that starts Werkzeug's single-process dev
    server, which is unsuitable for production.
  * It eagerly starts the background jobs (SLA checks, briefings, backups, …)
    the first time the module is imported, mirroring what run.py does.
  * It validates the runtime config (SECRET_KEY, JWT_SECRET, …) by eagerly
    invoking create_app() at import time so startup errors surface immediately
    in the WSGI server log rather than on the first HTTP request.

Usage examples:

    # Gunicorn + threads (recommended for production with Socket.IO threading mode)
    gunicorn \\
        --workers ${GUNICORN_WORKERS:-1} \\
        --threads ${GUNICORN_THREADS:-50} \\
        --timeout 120 \\
        --bind 0.0.0.0:5000 \\
        --access-logfile - \\
        --error-logfile - \\
        wsgi:app

    # Waitress (pure-Python, excellent on Windows / no-eventlet environments)
    waitress-serve --port 5000 --threads 32 wsgi:app

Socket.IO workers note
----------------------
The current Socket.IO instance uses ``async_mode="threading"`` and an in-memory
room registry.  For production WITHOUT a Redis / RabbitMQ message broker you
MUST use a single Gunicorn worker (``--workers 1``) — otherwise clients that
connect to different workers will never see each other's broadcast events
(e.g. ``issue_updated``, ``cluster_updated``).  Once a pub/sub broker is wired
in, you may safely raise ``GUNICORN_WORKERS``.
"""
import os

from app import create_app, start_background_jobs

# ── Eager app construction: fail FAST on config issues, not on first request
app = create_app()

# ── Start the APScheduler background job registry exactly once per process.
#    Gunicorn with preload_app=True (or --preload) will run this BEFORE forking,
#    so every worker inherits the scheduler objects.  We guard against double
#    initialization by checking a WSGI module-level sentinel.
_WSGI_SENTINEL_ATTR = "_smartcivic_wsgi_jobs_started"
if not getattr(app, _WSGI_SENTINEL_ATTR, False):
    scheduler = start_background_jobs(app)
    setattr(app, _WSGI_SENTINEL_ATTR, True)
    _ = scheduler  # local binding keeps the scheduler alive in this process


def _get_scheduler():
    """Expose the running scheduler for introspection / tests; always non-None."""
    return globals().get("scheduler") or start_background_jobs(app)


__all__ = ["app", "_get_scheduler"]
