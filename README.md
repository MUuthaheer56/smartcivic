# SmartCivic+

A Flask + MongoDB + Socket.IO civic issue reporting and management platform with AI classification (Gemini / rule-based fallback), role-based dashboards (citizen / officer / field worker), SLA tracking, simulation engines, and real-time notifications.

## Quick Start

### 1. Prerequisites
- Python 3.10+
- MongoDB 6+ running locally (or Atlas URI)
- `libmagic` system library: `sudo apt install libmagic1` (Debian/Ubuntu) or `brew install libmagic` (macOS)

### 2. Install Python dependencies
```bash
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure environment
```bash
cp .env.example .env
# Edit .env and set SECRET_KEY and JWT_SECRET to strong random strings
```

### 4. Prepare database
```bash
# Create indexes (required for geo queries)
python scripts/create_indexes.py

# Seed demo data (citizens / officers / workers + sample issues)
python seed_plus.py
```

### 5. Create upload folder
```bash
mkdir -p static/uploads/issues logs
```

### 6. Start the server
```bash
python run.py
# Server: http://127.0.0.1:5000
# Health: http://127.0.0.1:5000/api/health
```

## Demo Accounts (after seeding)

| Role | Email | Password |
|------|-------|----------|
| Citizen | citizen@smartcivic.com | smartcivic123 |
| Officer | officer@smartcivic.com | smartcivic123 |
| Worker | worker@smartcivic.com | smartcivic123 |

## Architecture

```
app.py            — Application factory, Socket.IO, APScheduler
config.py         — Env-based configuration
routes/           — Blueprints: auth, citizen, officer, worker, api/*
services/         — Business logic: complaint, assignment, AI, SLA, notifications, etc.
models/           — MongoDB document schemas and Marshmallow validation
templates/        — Jinja2 HTML templates per role
static/           — CSS, JS, uploaded images
scripts/          — DB index creation and backup utilities
logs/             — JSON rotating request/event logs (auto-created)
```

## Key Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SECRET_KEY` | ✅ | — | Flask session secret |
| `JWT_SECRET` | ✅ | — | JWT signing key |
| `MONGO_URI` | No | `mongodb://127.0.0.1:27017/smartcivic` | MongoDB connection |
| `GEMINI_API_KEY` | No | — | Google Gemini AI (falls back to rule-based) |
| `COOKIE_SECURE` | No | `false` | Set `true` for HTTPS deployments |
| `OSRM_BASE` | No | `http://router.project-osrm.org` | OSRM routing server |
