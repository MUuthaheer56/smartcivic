# ── SmartCivic+ Production Dockerfile ────────────────────────────────────────
# Python 3.10 slim base — small, secure, and compatible with every dep in
# requirements.txt (gunicorn, PyMongo, Pillow, onnxruntime/cv2 optional extras
# work on this base; the libmagic + gcc build tools remain for python-magic).
# ──────────────────────────────────────────────────────────────────────────────
FROM python:3.10-slim

WORKDIR /app

# Install system dependencies:
#   libmagic1      — used by python-magic for MIME sniffing of uploads
#   gcc / build-essential — fallback for any package that needs C extensions
#   curl           — useful for HEALTHCHECK against /api/health
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# ── Dependency layer (cached until requirements.txt changes) ─────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ── Application source ───────────────────────────────────────────────────────
COPY . .

# Create required runtime directories (uploads, logs, backups)
RUN mkdir -p logs static/uploads/issues backups

# ── Runtime configuration ────────────────────────────────────────────────────
EXPOSE 5000
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=5000

# ── Gunicorn / Socket.IO tuning notes ────────────────────────────────────────
# Socket.IO in this app uses async_mode="threading".  For production WITHOUT a
# shared message broker (Redis/RabbitMQ) we MUST use a single worker so that
# broadcast emit()s reach every connected client.  Threads inside that one
# worker handle concurrent HTTP traffic alongside the long-poll/WebSocket
# connections.  If you later add a Socket.IO message queue (Redis) you may
# raise GUNICORN_WORKERS to CPU_COUNT * 2 + 1.
#
# The defaults below are deliberately conservative and safe for ANY deployment
# — override with --env / docker-compose environment:
#
#     GUNICORN_WORKERS  — number of OS worker processes  (default: 1)
#     GUNICORN_THREADS  — threads per worker process    (default: 32)
#     GUNICORN_TIMEOUT  — worker silent-timeout seconds (default: 120)
# ──────────────────────────────────────────────────────────────────────────────
ENV GUNICORN_WORKERS=1 \
    GUNICORN_THREADS=32 \
    GUNICORN_TIMEOUT=120

# Entrypoint: invoke Gunicorn, binding to $PORT (injected by PaaS like Heroku /
# Render / Fly.io) or the default 0.0.0.0:5000.  wsgi module eagerly boots the
# Flask factory + background jobs (SLA sweeps, AI briefings, backups, etc.).
CMD ["sh", "-c", \
    "exec gunicorn \
        --workers ${GUNICORN_WORKERS} \
        --threads ${GUNICORN_THREADS} \
        --timeout ${GUNICORN_TIMEOUT} \
        --graceful-timeout 30 \
        --keep-alive 5 \
        --bind 0.0.0.0:${PORT:-5000} \
        --forwarded-allow-ips='*' \
        --proxy-protocol \
        --access-logfile - \
        --error-logfile - \
        --log-level info \
        --capture-output \
        wsgi:app"]

# Healthcheck uses the /api/health endpoint the app already exposes.  This
# causes Docker / ECS / ECS Fargate / Kubernetes to restart the container if
# MongoDB disappears or the Flask factory fails.
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -fsS http://127.0.0.1:${PORT:-5000}/api/health || exit 1
