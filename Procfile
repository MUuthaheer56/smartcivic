# SmartCivic+ Procfile — for Heroku / Dokku / Render / Fly.io PaaS deployments
#
# `web` process: Gunicorn with threads and a single worker (required for
# Socket.IO room broadcasts when no shared message broker is configured).
# Override GUNICORN_THREADS / GUNICORN_WORKERS via env vars on the platform.
web: gunicorn --workers ${GUNICORN_WORKERS:-1} --threads ${GUNICORN_THREADS:-32} --timeout ${GUNICORN_TIMEOUT:-120} --keep-alive 5 --bind 0.0.0.0:${PORT:-5000} --forwarded-allow-ips='*' --access-logfile - --error-logfile - --log-level info --capture-output wsgi:app
