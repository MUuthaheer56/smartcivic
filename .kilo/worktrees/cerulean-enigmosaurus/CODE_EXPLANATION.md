# SmartCivic — Comprehensive Code Explanation & Architectural Blueprint

This document provides a single, authoritative, file-by-file technical reference for the **SmartCivic** municipal issue-management platform.
For every module, service, model, configuration key, and machine learning component, this guide explains:
1. **What does this code do?**
2. **Why was this approach / algorithm / model chosen?**
3. **If I change this, what breaks or changes elsewhere?**

---

## 🏗️ Architecture Map

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                   CLIENT INTERFACE                                    │
│             (Web Browsers / Mobile App Clients / Socket.IO WS / REST API Clients)       │
└───────────────────────────┬────────────────────────────────────────────┘
                                            │ HTTP / WebSocket Requests
                                            ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                 FLASK APP FACTORY (app.py)                             │
│                  (Config, Rate Limiter, Socket.IO, Security Headers, Error Handlers)     │
└──────┬────────────────────────────────────┬────────────────────────────────────┬───────┘
       │                                    │                                    │
       ▼                                    ▼                                    ▼
┌───────────────────────────┐  ┌───────────────────────────┐  ┌───────────────────────────┐
│     PAGE BLUEPRINTS       │  │     REST API BLUEPRINTS   │  │   BACKGROUND SCHEDULER    │
│ (auth, citizen, officer,  │  │ (issues, workers, map,    │  │ (APScheduler background   │
│          worker)          │  │ analytics, civicpulse)    │  │   jobs & SLA sweeps)      │
└──────────────┬────────────┘  └────────────┬──────────────┘  └────────────┬──────────────┘
               │                            │                              │
               └────────────────────────────┼──────────────────────────────┘
                                            │ Route Handlers Invocation
                                            ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                   SERVICE LAYER                                        │
│  ┌────────────────────────┐  ┌────────────────────────┐  ┌──────────────────────────┐  │
│  │   complaint_service    │  │       ai_service       │  │    assignment_service    │  │
│  └───────────┬────────────┘  └───────────┬────────────┘  └────────────┬─────────────┘  │
│              │                           │                            │                │
│  ┌───────────┴────────────┐  ┌───────────┴────────────┐  ┌────────────┴─────────────┐  │
│  │    duplicate_service   │  │      sla_service       │  │     priority_service     │  │
│  └────────────────────────┘  └────────────────────────┘  └──────────────────────────┘  │
│  ┌────────────────────────┐  ┌────────────────────────┐  ┌──────────────────────────┐  │
│  │     routing_service    │  │  notification_service  │  │      worker_service      │  │
│  └────────────────────────┘  └────────────────────────┘  └──────────────────────────┘  │
└──────┬────────────────────────────────────┬────────────────────────────────────┬───────┘
       │                                    │                                    │
       ▼                                    ▼                                    ▼
┌───────────────────────────┐  ┌───────────────────────────┐  ┌───────────────────────────┐
│    MACHINE LEARNING       │  │       UTILITIES           │  │     DATA MODELS & DB      │
│  (ml/yolo_runner.py ONNX) │  │  (validators, geo_utils,  │  │ (models/*.py MongoDB PyMongo)│
│  (Gemini LLM Vision/Text) │  │       image_utils)        │  │  Collections: users,      │
│                           │  │                           │  │  issues, workers, etc.    │
└───────────────────────────┘  └───────────────────────────┘  └───────────────────────────┘
```

---

## 📊 Change Impact Matrix

| Component / Config Key | `complaint_service` | `ai_service` | `duplicate_service` | `priority_service` | `sla_service` | `assignment_service` | `issue_routes` |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| `Config.DUPLICATE_RADIUS_METERS` | No effect | No effect | **Behavioural** — Alters duplicate clustering distance window | No effect | No effect | No effect | No effect |
| `Config.DUPLICATE_THRESHOLD` | No effect | No effect | **Behavioural** — Changes strictness of duplicate text/geo matching | No effect | No effect | No effect | No effect |
| `Config.SLA_HOURS` | **Behavioural** — Modifies issue deadline calculations | No effect | No effect | No effect | **Breaking** — Recalculates default deadlines | No effect | No effect |
| `Config.YOLO_CONFIDENCE_THRESHOLD` | No effect | **Behavioural** — Changes ONNX vision defect acceptance sensitivity | No effect | No effect | No effect | No effect | No effect |
| `ai_service.analyze_image()` return shape | **Breaking** — `fuse_predictions()` receives missing fields | — | No effect | No effect | No effect | No effect | No effect |
| `ai_service.fuse_predictions()` weighting | **Behavioural** — Changes issue classification & severity assignments | — | No effect | **Behavioural** — Alters initial priority scores | No effect | No effect | No effect |
| `LEGAL_TRANSITIONS` state dict | **Breaking** — `update_status()` rejects valid or invalid transitions | No effect | No effect | No effect | No effect | **Breaking** — `assign_worker()` fails if status transition blocked | **Breaking** — Status PATCH/POST endpoints return 422 |
| `assignment_service.recommend_workers()` scoring formula | No effect | No effect | No effect | No effect | No effect | **Behavioural** — Changes order of recommended field workers | No effect |
| `models/user.py` schema (`is_available` field) | No effect | No effect | No effect | No effect | No effect | **Breaking** — Workers excluded from assignment queue | No effect |
| `models/issue.py` GeoJSON format | **Breaking** — Spatial queries throw BadValue index errors | No effect | **Breaking** — Near sphere queries fail | No effect | No effect | **Breaking** — Proximity calculations fail | **Breaking** — Latitude/longitude validation fails |

---

## 📁 File-by-File Technical Guide

---

## FILE: config.py

### Purpose
Provides centralized, immutable application configuration values loaded from environment variables or `.env` file. It establishes master system constants including SLA thresholds, spatial clustering limits, ML paths, authentication token lifetimes, and department mappings. All services and blueprints import `Config` from this file.

---

### CLASS: Config

**What it does**
Defines static configuration attributes for Flask security, MongoDB connections, JWT expirations, upload boundaries, SLA targets, spatial duplicate detection thresholds, ONNX ML model paths, OSRM routing URLs, and department/skill mappings.

**Why this approach was chosen**
- Environment variable driven configuration adheres to 12-Factor App methodology.
- Centralizing thresholds (e.g. 200m duplicate radius, 4-hour critical SLA) ensures single-point updateability across all service layers without code duplication.

**Line-by-line breakdown**

| Line(s) | Code | What it does | What breaks if you change it |
|:---|:---|:---|:---|
| 11–18 | `def _require_secret(name: str) -> str:` | Enforces presence of vital secrets (`SECRET_KEY`, `JWT_SECRET`) at startup | Remove check → missing secrets default to empty strings, creating fatal security vulnerabilities in JWT signing |
| 21–22 | `SECRET_KEY`, `JWT_SECRET` | Security keys for Flask session signing and JWT HMAC token generation | Change after deployment → all existing user sessions and JWT tokens become immediately invalid |
| 23 | `MONGO_URI` | Connection URI string for MongoDB database | Invalid URI → application fails to connect to database on launch |
| 27–28 | `JWT_ACCESS_EXPIRES`, `JWT_REFRESH_EXPIRES` | Expiration time windows for JWT tokens (30 mins access, 7 days refresh) | Set too short → users logged out constantly; set too long → compromised tokens remain active longer |
| 33–34 | `MAX_UPLOAD_SIZE`, `MAX_IMAGE_BYTES` | File upload cap set to 10MB | Set too small → valid high-resolution camera photos rejected; set too large → vulnerability to storage exhaustion |
| 40 | `SLA_HOURS` | Target resolution hours by severity (`critical: 4`, `high: 24`, `medium: 72`, `low: 168`) | Remove critical key → SLA calculation raises `KeyError` during complaint creation |
| 44–45 | `DUPLICATE_RADIUS_METERS`, `DUPLICATE_THRESHOLD` | 200m radius and 0.85 similarity score boundary for duplicate detection | Set radius to 5000m → complaints across the city get false-flagged as duplicates |
| 51–52 | `YOLO_MODEL_PATH`, `YOLO_CONFIDENCE_THRESHOLD` | ONNX model filepath and 0.40 confidence cutoff for defect detection | Wrong path → vision analysis falls back gracefully to `available: false`; threshold too high (0.95) → misses real potholes |
| 55–57 | `ROUTING_ENGINE_URL`, `OSRM_BASE` | Base URLs for OSRM road-network route computation | Invalid URL → route service cannot reach OSRM, falling back to `available: false` |
| 60–67 | `CATEGORY_TO_DEPARTMENT` | Dict mapping complaint category (`road`, `water`) to municipal department | Incorrect mapping → issue assigned to wrong department queue |
| 70–77 | `ISSUE_TYPE_TO_SKILLS` | Dict mapping issue type (`pothole`, `water_leak`) to worker skills | Remove mapping → worker recommendation engine cannot match required field skills |

**Connections to other files**
- Called by: `app.py`, `services/complaint_service.py`, `services/ai_service.py`, `services/duplicate_service.py`, `services/assignment_service.py`, `services/sla_service.py`, `ml/yolo_runner.py`, `routes/api/issues.py`

**If you change this file**
- Modifying `DUPLICATE_RADIUS_METERS` changes duplicate clustering behavior system-wide.
- Modifying `SLA_HOURS` changes calculated resolution deadlines for new complaints.

---

## FILE: extensions.py

### Purpose
In standard Flask architectures, `extensions.py` holds instances of Flask extensions (e.g. `db`, `jwt`, `socketio`, `limiter`) so they can be initialized without circular import dependencies when using the Application Factory pattern (`create_app()`).

---

### SECTION: Extension Instantiation

**What it does**
Instantiates unattached extension objects that are later bound to the Flask application instance inside `app.py` via `.init_app(app)`.

**Why this approach was chosen**
- The Application Factory pattern allows creating multiple app instances for testing, staging, and production cleanly without global state pollution.

**Line-by-line breakdown**

| Line(s) | Code | What it does | What breaks if you change it |
|:---|:---|:---|:---|
| 1–10 | Extension declarations | Holds unattached Flask extension singletons | Instantiating with `app` directly at module level → causes circular imports when routes import extensions |

**Connections to other files**
- Called by: `app.py`, `routes/*.py`

---

## FILE: app.py

### Purpose
Functions as the core Application Factory for SmartCivic+. It initializes PyMongo database handles, Socket.IO real-time event servers, rate limiters, security headers, background schedulers (APScheduler), error handlers, and registers all page and REST API blueprints.

---

### FUNCTION: create_app()

**What it does**
Configures and constructs the Flask WSGI application instance. Loads configuration, attaches extensions, registers all route blueprints, adds HTTP security headers, configures CSP policies, and installs global exception handlers.

**Why this approach was chosen**
- Application factory allows test suites (`test_e2e_verification.py`, `test_app_plus.py`) to spawn isolated test clients with `TESTING = True`.

**Line-by-line breakdown**

| Line(s) | Code | What it does | What breaks if you change it |
|:---|:---|:---|:---|
| 19–24 | `client = MongoClient(mongo_uri)` `db = client[db_name]` | Establishes PyMongo database handle at module level for thread safety | Remove this → all service and route imports referencing `db` break |
| 27–28 | `socketio = SocketIO(...)`, `limiter = Limiter(...)` | Initializes Socket.IO and in-memory security rate limiter | Remove limiter → API endpoints exposed to brute-force and Denial-of-Service attacks |
| 52–75 | `app.register_blueprint(...)` | Registers auth, citizen, officer, worker, issues, map, analytics blueprints | Omit blueprint registration → routes under that blueprint return 404 Not Found |
| 111–125 | `@app.before_request def load_user_context():` | Extracts JWT from `access_token` cookie and populates `g.current_user` | Remove hook → `g.current_user` remains None, breaking authenticated page renders |
| 127–150 | `@app.after_request def add_security_headers(response):` | Appends HSTS, X-Frame-Options, CSP, and X-Content-Type-Options headers | Remove headers → web app vulnerable to clickjacking and XSS script injection |
| 166–185 | `@app.errorhandler(Exception)` | Global catch-all handler returning structured JSON for API routes and error pages for web UI | Remove handler → unhandled exceptions expose raw Python tracebacks to client |

**Connections to other files**
- Calls: `config.Config`, `routes.auth.auth_bp`, `routes.api.issues.issues_api_bp`, `routes.api.map.map_api_bp`, `scripts.create_indexes.setup_indexes()`
- Called by: `run.py`, `test_e2e_verification.py`, `test_app_plus.py`

---

### FUNCTION: start_background_jobs(app)

**What it does**
Starts an APScheduler background scheduler executing periodic maintenance tasks: SLA sweeps (every 15 mins), briefing/health score generation (every 30 mins), predictive hotspot calculation (weekly), infrastructure health recalculation (every 6 hours), and database backups (daily).

**Why this approach was chosen**
- Running background tasks in dedicated scheduler threads ensures heavy analytics and sweeps do not block HTTP request-response cycles.

**Line-by-line breakdown**

| Line(s) | Code | What it does | What breaks if you change it |
|:---|:---|:---|:---|
| 199–211 | `scheduler.add_job(sla_sweep_job, 'interval', seconds=900)` | Executes periodic SLA status check across all open complaints | Remove job → SLA breaches never detected automatically until manual dashboard refresh |
| 277–278 | `if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not app.debug:` | Prevents duplicate scheduler execution when Flask dev reloader is active | Remove check → background jobs run twice concurrently during local development |

---

## FILE: models/user.py

### Purpose
Defines the User document schema, citizen civic reputation tiers, and helper function `create_user_doc()` for building structured user documents (`resident`, `officer`, `worker`).

---

### FUNCTION: create_user_doc()

**What it does**
Constructs a normalized MongoDB user document dictionary based on role, initializing role-specific fields such as `civic_score` and `reports_submitted` for residents, or `skills`, `is_available`, and `status: "available"` for workers.

**Why this approach was chosen**
- MongoDB's document model allows storing role-specific sub-schemas within a single `users` collection without requiring sparse relational tables or multi-table JOINs.

**Line-by-line breakdown**

| Line(s) | Code | What it does | What breaks if you change it |
|:---|:---|:---|:---|
| 23–24 | `normalized_role = "resident" if role in ["resident", "citizen"] else role` | Normalizes legacy `"citizen"` role string to `"resident"` | Remove normalization → queries filtering by `role: "resident"` miss legacy citizen accounts |
| 34–40 | `if normalized_role in ["resident", "citizen"]:` | Populates civic score (0) and role tier (`"reporter"`) for resident users | Omit fields → resident dashboard crashes when reading missing `civic_score` |
| 41–52 | `elif normalized_role == "worker":` | Populates worker skills, default GeoJSON location, `active_assignments`, `is_available: True`, `status: "available"` | Omit `status: "available"` → worker recommendation engine rejects new worker as unavailable |

**Connections to other files**
- Called by: `routes/auth.py → register()`

---

## FILE: models/issue.py

### Purpose
Defines the core Issue schema dictionary helper `create_issue_doc()`, system enum arrays (`STATUSES`, `CATEGORIES`, `DEPARTMENTS`, `SEVERITIES`), and Marshmallow validation schemas.

---

### FUNCTION: create_issue_doc()

**What it does**
Constructs the foundational document template for a municipal complaint, including GeoJSON Point location (`[longitude, latitude]`), status (`"submitted"`), empty resolution proof containers, SLA timestamps, and duplicate tracking fields.

**Why this approach was chosen**
- Storing coordinates strictly as GeoJSON `{"type": "Point", "coordinates": [lng, lat]}` is mandatory for MongoDB 2dsphere spatial indexing and `$near` proximity queries.

**Line-by-line breakdown**

| Line(s) | Code | What it does | What breaks if you change it |
|:---|:---|:---|:---|
| 36–39 | `"location": {"type": "Point", "coordinates": [float(lng), float(lat)]}` | Formats valid GeoJSON Point structure | Swap lat/lng order to `[lat, lng]` → MongoDB 2dsphere index throws `Point must only contain two numeric elements` or places points in the wrong hemisphere |
| 48–52 | `"status": "submitted"`, `"priority": "medium"` | Sets initial complaint lifecycle state and baseline priority | Change initial status → breaks status transition state machine validation |

**Connections to other files**
- Called by: `services/complaint_service.py → create_complaint()`

---

## FILE: services/auth_service.py

### Purpose
Handles user authentication, password hashing, JWT token generation, role authorization verification, and current user extraction from requests.

---

### FUNCTION: generate_tokens(), require_auth, require_role()

**What it does**
- `hash_password()` / `check_password()`: Secures passwords using Werkzeug's salted `scrypt` / `pbkdf2:sha256` hashing algorithm.
- `generate_tokens()`: Issues signed HS256 JWT access (30 mins) and refresh (7 days) tokens containing user ID, role, and ward.
- `require_auth`: Flask decorator verifying JWT tokens from `Authorization: Bearer <token>` header or `access_token` HttpOnly cookie.
- `require_role(*roles)`: Decorator enforcing role-based access control (RBAC).

**Why this approach was chosen**
- Salted key-stretching hashing (pbkdf2/scrypt) protects stored passwords against rainbow table and GPU dictionary attacks.
- Stateless JWT authentication allows scaling API clients without server-side session lookup overhead.
- Prioritizing `Authorization: Bearer` headers while falling back to HttpOnly cookies allows seamless support for both API clients and browser sessions while preventing XSS token theft.

**Line-by-line breakdown**

| Line(s) | Code | What it does | What breaks if you change it |
|:---|:---|:---|:---|
| 21–22 | `generate_password_hash(password)`, `check_password_hash(...)` | Hashes and verifies passwords securely | Use plain SHA-256 → password database vulnerable to instant rainbow-table cracking |
| 30–35 | `jwt.encode(payload, secret, algorithm="HS256")` | Signs JWT token containing user identity and expiration claims | Omit `exp` claim → tokens never expire, creating perpetual access risk |
| 85–98 | `auth_header = request.headers.get("Authorization")` | Prioritizes Bearer token header over cookies | Omit header check → REST API testing tools and mobile apps using headers fail auth |

**Connections to other files**
- Called by: `routes/auth.py`, `routes/api/*.py`, `app.py`

---

## FILE: services/ai_service.py

### Purpose
The central AI orchestration engine. Combines rule-based keyword heuristics, Gemini LLM text parsing/multilingual translation, local ONNX YOLOv8 image defect detection, and multimodal prediction fusion.

---

### FUNCTION: analyze_complaint_text(), analyze_complaint_image(), fuse_complaint_predictions()

**What it does**
- **Text Analysis**: Sends text to Gemini LLM (or keyword heuristic fallback when offline/quota-exceeded) to classify category (`road`, `water`), issue type (`pothole`), severity (`critical`, `high`, `medium`, `low`), and returns `confidence_type: "model"` or `"heuristic"`.
- **Image Analysis**: Calls `ml/yolo_runner.py` for CPU ONNX inference or Gemini Vision. If model or image is unavailable, strictly returns `available: false` with reasoning.
- **Fusion**: Blends text and image predictions. When high-confidence image detection is available, image severity overrides text severity (e.g. visual road collapse overrides mild text description).

**Why this approach was chosen**
- **LLM vs Keyword**: LLMs understand context, slang, and Indic multilingual descriptions ("rasta kharab hai", "big pit on main road") far better than rigid regex matchers.
- **Model vs Heuristic Confidence**: Tracking `confidence_type` distinguishes genuine AI inference from fallback rules, which is critical for officer auditability.
- **Zero Operating Cost Graceful Degradation**: When Gemini API quota is exceeded (HTTP 429), the system seamlessly falls back to local rule-based heuristics without crashing or blocking complaint submission.

**Line-by-line breakdown**

| Line(s) | Code | What it does | What breaks if you change it |
|:---|:---|:---|:---|
| 110–122 | `analyze_complaint_text(description)` | Executes Gemini text prompt or local rule fallback | Remove fallback → complaints fail to submit when Gemini API experiences outage or rate limits |
| 150–175 | `analyze_complaint_image(image_path)` | Invokes `run_yolo_inference()` | Return fake detections when unavailable → system presents false AI predictions to municipal officers |
| 230–285 | `fuse_complaint_predictions(ai_text, ai_img)` | Fuses text and image predictions based on confidence scores | Always favor text → visual critical hazards (e.g. massive road sinkhole) get downgraded to low severity |

**Connections to other files**
- Calls: `ml/yolo_runner.py → run_yolo_inference()`, Google Gemini API
- Called by: `services/complaint_service.py → create_complaint()`

---

## FILE: services/duplicate_service.py

### Purpose
Provides spatial and textual duplicate detection logic to identify duplicate civic reports filed near existing open complaints.

---

### FUNCTION: detect_duplicate(), calculate_similarity()

**What it does**
Queries nearby open issues within `DUPLICATE_RADIUS_METERS` (200m), computes spatial proximity via Haversine formula, calculates text similarity (word overlap / TF-IDF cosine score), and flags complaints with combined similarity $\ge 0.85$ as duplicates (`status: "duplicate"`).

**Why this approach was chosen**
- Haversine formula accurately measures spherical surface distance on Earth at city-block scale.
- Combining spatial distance (70% weight) and description similarity (30% weight) prevents flagging different issues at the same location (e.g. street light failure vs pothole at same intersection) while accurately clustering identical pothole reports.

**Line-by-line breakdown**

| Line(s) | Code | What it does | What breaks if you change it |
|:---|:---|:---|:---|
| 25–35 | `haversine(coord1, coord2)` | Calculates geodesic distance in kilometers between two lat/lng pairs | Use Euclidean distance → severe projection distortion at non-equatorial latitudes |
| 45–60 | `combined_sim = (geo_sim * 0.7) + (text_sim * 0.3)` | Weights geographic proximity higher than text phrasing | Weight text 100% → two identical descriptions 10 km apart get falsely marked as duplicates |
| 70–80 | `if combined_sim >= Config.DUPLICATE_THRESHOLD:` | Flags duplicate when similarity meets or exceeds 0.85 threshold | Lower threshold to 0.40 → distinct issues across the ward get suppressed as duplicates |

**Connections to other files**
- Calls: `services/route_service.py → haversine()`
- Called by: `services/complaint_service.py → create_complaint()`, `services/ai_service.py → detect_duplicates()`

---

## FILE: services/priority_service.py

### Purpose
Calculates dynamic priority scores (`priority_score`) for complaints to determine queue ordering in officer and worker dashboards.

---

### FUNCTION: calculate_priority()

**What it does**
Computes a numerical priority score (0 to 100+) by evaluating baseline severity (`critical: 80`, `high: 60`, `medium: 40`, `low: 20`), community confirmations count (+5 per confirmation), duplicate child count, age decay, and emergency flags (force set to 100.0).

**Why this approach was chosen**
- Severity is an static assessment of hazard level, whereas Priority is dynamic. A medium-severity water leak confirmed by 30 citizens demands higher operational urgency than an unconfirmed single report.

**Line-by-line breakdown**

| Line(s) | Code | What it does | What breaks if you change it |
|:---|:---|:---|:---|
| 15–20 | `base_score = {"critical": 80, "high": 60, "medium": 40, "low": 20}.get(sev, 40)` | Sets base score from severity level | Remove base score → all complaints default to equal priority regardless of danger |
| 25–30 | `confirm_bonus = min(30.0, confirmation_count * 5.0)` | Adds up to 30 bonus points based on citizen confirmations | Remove confirmation factor → widespread community issues lose priority boost |

**Connections to other files**
- Called by: `services/complaint_service.py`, `services/sla_service.py`

---

## FILE: services/sla_service.py

### Purpose
Calculates SLA resolution deadlines based on severity, checks breach status, and calculates remaining time windows.

---

### FUNCTION: assign_sla(), check_sla_status()

**What it does**
- `assign_sla()`: Assigns resolution deadline datetime (`created_at + SLA_HOURS[severity]`).
- `check_sla_status()`: Compares current time against `sla_deadline`. If `utcnow() > deadline` and issue is unresolved, marks `sla.breached = True` and triggers officer notifications.

**Why this approach was chosen**
- Storing deadline as UTC datetime enables indexed database filtering (`sla_deadline: {"$lte": now}`) for automated breach sweeps.

**Line-by-line breakdown**

| Line(s) | Code | What it does | What breaks if you change it |
|:---|:---|:---|:---|
| 15–22 | `hours = Config.SLA_HOURS.get(severity, 72)` | Fetches target hours for severity (`critical: 4h`, `high: 24h`) | Remove lookup fallback → invalid severity raises UnboundLocalError during SLA calculation |
| 35–45 | `if now > deadline and not issue.get("sla", {}).get("breached"):` | Flags SLA breach when deadline is exceeded | Omit check → breached complaints remain marked on-track in officer analytics |

**Connections to other files**
- Called by: `services/complaint_service.py`, `app.py → start_background_jobs()`

---

## FILE: services/assignment_service.py

### Purpose
Manages worker recommendation scoring, skill matching, worker assignment binding, worker load incrementing, and state synchronization.

---

### FUNCTION: recommend_workers(), assign_worker()

**What it does**
- `recommend_workers()`: Filters available workers by department and required skills (`road_repair`, `pothole_repair`), computes worker distance to issue, calculates load score (fewer active jobs = higher score), and returns top candidates.
- `assign_worker()`: Binds worker to issue, creates `assignments` collection record, appends entry to `assignment_history`, transitions issue status to `"assigned"`, updates worker status to `"assigned"`, and sets worker `is_available = False`.

**Why this approach was chosen**
- Separating recommendation from assignment empowers officers to make human-in-the-loop decisions rather than relying on fully automated dispatch.
- Simultaneously updating 4 states (Issue worker ref, Issue assignment dict, Issue status, Worker status) guarantees data consistency across worker and officer dashboards.

**Line-by-line breakdown**

| Line(s) | Code | What it does | What breaks if you change it |
|:---|:---|:---|:---|
| 45–48 | `if required_skills and not any(s in skills for s in required_skills): continue` | Filters out workers lacking required skills for the job | Remove check → electrical workers get assigned to asphalt road collapse repairs |
| 121–124 | `if w_status == "assigned" or w_avail is False:` | Checks worker availability before assigning | Remove check → single worker can be assigned infinite concurrent jobs simultaneously |
| 138–167 | `db.issues.update_one(...)`, `db.workers.update_one(...)` | Executes 4-part state update on issue and worker documents | Omit worker status update → worker dashboard task list fails to query assigned job |

**Connections to other files**
- Called by: `routes/api/issues.py → assign_issue_route()`, `routes/api/issues.py → get_issue_worker_recommendations()`

---

## FILE: services/routing_service.py / services/route_service.py

### Purpose
Provides road-network route navigation calculations for field workers navigating from their current position to assigned issue coordinates.

---

### FUNCTION: get_route()

**What it does**
Sends HTTP GET request to OSRM (Open Source Routing Machine) driving API (`http://router.project-osrm.org/route/v1/driving/lng1,lat1;lng2,lat2`). Parses returned geometry polylines into coordinate arrays, distance in meters, and travel duration in seconds. If OSRM is unreachable or times out, returns `{"available": false, "reason": "routing_service_unavailable"}`.

**Why this approach was chosen**
- OSRM uses OpenStreetMap road network data to calculate real driving paths along actual streets rather than straight lines.
- Returning explicit `available: false` during OSRM outages strictly prevents sending field workers along unsafe straight lines that ignore rivers, buildings, and one-way streets.

**Line-by-line breakdown**

| Line(s) | Code | What it does | What breaks if you change it |
|:---|:---|:---|:---|
| 20–25 | `requests.get(url, timeout=Config.ROUTING_TIMEOUT_SECONDS)` | Fetches route geometry from OSRM with 5s timeout cap | Omit timeout → slow OSRM response hangs Flask worker threads indefinitely |
| 35–45 | `geometry = data["routes"][0]["geometry"]` | Extracts road-network waypoint coordinates | Fallback to 2-point line on failure → Navigation UI displays straight line passing through buildings |

**Connections to other files**
- Called by: `routes/api/map.py → calculate_route()`

---

## FILE: services/complaint_service.py

### Purpose
The primary application orchestrator. Coordinates complaint creation, language translation, AI prediction extraction, duplicate clustering, SLA initialization, status transition enforcement, and audit logging.

---

### FUNCTION: create_complaint(), update_status()

**What it does**
- `create_complaint()`: Main workflow pipeline: Translates text $\rightarrow$ Creates base document $\rightarrow$ Runs AI text analysis $\rightarrow$ Runs ONNX/Gemini image analysis $\rightarrow$ Fuses predictions $\rightarrow$ Scans duplicates $\rightarrow$ Assigns SLA $\rightarrow$ Saves to MongoDB $\rightarrow$ Dispatches Socket.IO notification.
- `update_status()`: Enforces state machine transitions against `LEGAL_TRANSITIONS` dict (`submitted → under_review → verified → assigned → en_route → in_progress → resolved → closed`), pushes history entry, and logs audit trail.

**Why this approach was chosen**
- Orchestrating multi-step complaint handling in a single service function ensures transactional workflow consistency across AI, duplicate, SLA, and audit modules.

**Line-by-line breakdown**

| Line(s) | Code | What it does | What breaks if you change it |
|:---|:---|:---|:---|
| 17–32 | `LEGAL_TRANSITIONS = {...}` | Defines legal status transition state machine dictionary | Remove dict validation → invalid status changes (`submitted → resolved`) allowed without verification |
| 123–128 | `final_prediction = ai_service.fuse_complaint_predictions(...)` | Combines text and visual AI findings | Omit fusion → final complaint prediction relies solely on raw text description |
| 325–331 | `if new_status not in allowed: raise ValueError(...)` | Rejects illegal status transitions | Remove check → state machine corrupted; workers can mark unassigned issues resolved |

**Connections to other files**
- Calls: `services/ai_service.py`, `services/duplicate_service.py`, `services/sla_service.py`, `services/audit_service.py`, `services/notification_service.py`
- Called by: `routes/api/issues.py`

---

## FILE: services/worker_service.py

### Purpose
Handles worker task retrieval, distance calculation from worker to tasks, and worker profile availability lookups.

---

### FUNCTION: get_worker_tasks()

**What it does**
Queries `issues` collection for complaints where `worker_id == worker_id` (or `assignment.worker_id == worker_id`) and status is active (`assigned`, `en_route`, `in_progress`). Computes Haversine distance from worker's current location to each task and returns sorted task list.

**Why this approach was chosen**
- Querying `assignment.worker_id` alongside root `worker_id` ensures compatibility across legacy and current issue document formats.

**Line-by-line breakdown**

| Line(s) | Code | What it does | What breaks if you change it |
|:---|:---|:---|:---|
| 15–25 | `query = {"$or": [{"worker_id": ObjectId(w_id)}, {"assignment.worker_id": w_id}]}` | Fetches active tasks assigned to specific worker | Remove `$or` check → tasks assigned via assignment service missing from worker dashboard |

**Connections to other files**
- Called by: `routes/api/workers.py → get_worker_tasks_route()`

---

## FILE: services/notification_service.py

### Purpose
Handles real-time WebSocket event dispatch via Flask-SocketIO to specific user rooms, ward rooms, or officer role rooms.

---

### FUNCTION: send()

**What it does**
Emits structured Socket.IO notification payloads (e.g. `complaint_created`, `complaint_assigned`, `issue_resolved`) to target rooms (`user_<id>`, `ward_<name>`, `role_officer`) under the `/civic` WebSocket namespace.

**Why this approach was chosen**
- Room-based WebSocket emissions ensure push notifications are delivered strictly to authorized recipients (e.g. assigned worker or reporting resident) in real time without polling overhead.

**Line-by-line breakdown**

| Line(s) | Code | What it does | What breaks if you change it |
|:---|:---|:---|:---|
| 25–35 | `socketio.emit(event, payload, room=room, namespace="/civic")` | Emits real-time event to specific Socket.IO room | Omit namespace → WebSocket clients listening on `/civic` fail to receive push updates |

**Connections to other files**
- Called by: `services/complaint_service.py`, `services/assignment_service.py`, `routes/api/issues.py`

---

## FILE: routes/auth.py

### Purpose
Handles HTTP endpoints for user registration (`POST /api/auth/register`), authentication (`POST /api/auth/login`), session token refresh (`POST /api/auth/refresh`), logout (`POST /api/auth/logout`), and profile fetch (`GET /api/auth/me`).

---

### FUNCTION: register(), login()

**What it does**
- `register()`: Validates input fields, checks email uniqueness, verifies admin invite code for staff roles (`officer`, `worker`), hashes password, and creates user document.
- `login()`: Validates credentials, checks account lockout status (10 failed attempts = 15 min lock), updates `last_login`, generates JWT tokens, and sets secure HttpOnly cookies (`access_token`, `refresh_token`).

**Why this approach was chosen**
- Enforcing Admin Invite Code check prevents unauthorized registration of officer/worker elevated privilege accounts.
- Returning tokens in both JSON response body and HttpOnly cookies provides maximum flexibility for API clients and web browsers while protecting web users against XSS token theft.

**Line-by-line breakdown**

| Line(s) | Code | What it does | What breaks if you change it |
|:---|:---|:---|:---|
| 124–132 | `if role in ["officer", "worker"]:` `if not invite_code or not hmac.compare_digest(...)` | Enforces Admin Invite Code validation for staff roles | Remove check → any anonymous public user can register as a municipal officer |
| 180–190 | `if failed_count >= 10: lock_time = now + timedelta(minutes=15)` | Locks account for 15 minutes after 10 failed login attempts | Remove lockout → system vulnerable to automated online password brute-force attacks |
| 232–234 | `response.set_cookie("access_token", access_token, httponly=True...)` | Sets access token in secure HttpOnly cookie | Remove `httponly=True` → client-side XSS vulnerabilities can read and exfiltrate auth tokens |

**Connections to other files**
- Calls: `models/user.py → create_user_doc()`, `services/auth_service.py`
- Called by: Client web browsers and mobile apps

---

## FILE: routes/api/issues.py

### Purpose
The main REST API blueprint for complaints (`/api/issues`). Implements complaint submission, single issue fetch, issue list query with filters, classification override, status updates, worker recommendations, worker assignment, resolution proof submission, and audit log inspection.

---

### FUNCTION: create_issue(), get_issue(), list_issues(), update_issue_status_route(), assign_issue_route(), submit_resolution_proof()

**What it does**
- `POST /api/issues`: Accepts multipart/form-data complaint submission, performs MIME/size validation on uploaded image, saves file, and invokes `complaint_service.create_complaint()`.
- `GET /api/issues/<id>`: Returns full complaint detail. Includes IDOR ownership check (residents can only view their own issues; officers restricted to assigned ward).
- `PATCH /api/issues/<id>/status`: Updates complaint status.
- `PATCH /api/issues/<id>/classification`: Officer override route for category/severity/department. Recalculates SLA deadline while preserving original AI prediction untouched.
- `POST /api/issues/<id>/assignment`: Officer route binding worker to complaint.
- `POST /api/issues/<id>/resolution`: Worker route uploading resolution proof photo (`after_image`) and transitioning status to `"resolved"`.

**Why this approach was chosen**
- Strict IDOR checks (`str(issue["citizen_id"]) == str(g.current_user["_id"])`) prevent unauthorized residents from inspecting other citizens' personal complaint details.
- Preserving `ai_prediction` untouched when an officer submits a classification override ensures auditability for AI performance evaluations.

**Line-by-line breakdown**

| Line(s) | Code | What it does | What breaks if you change it |
|:---|:---|:---|:---|
| 23–60 | `validate_image_file(file)` | Validates image file extension, size cap (10MB), and header MIME type via PIL verification | Remove check → malicious users can upload executable scripts or huge files |
| 179–181 | `if user_role in ["resident", "citizen"] and str(issue.get("citizen_id")) != str(g.current_user["_id"]): return 403` | IDOR check blocking residents from fetching other users' complaints | Remove check → security flaw allowing any resident to view all city complaints |
| 395–400 | `update_fields["ai_analysis.ai_prediction"] = ai_prediction` | Preserves original AI prediction untouched during officer override | Overwrite `ai_prediction` → destroys baseline data required for AI accuracy auditing |
| 903–905 | `if assigned_w != str(g.current_user["_id"]): return 403` | IDOR check ensuring only assigned worker can submit resolution proof | Remove check → unauthorized workers can mark other workers' tasks resolved |

**Connections to other files**
- Calls: `services/complaint_service.py`, `services/assignment_service.py`, `services/verification_service.py`, `services/sla_service.py`
- Called by: Client web applications & mobile clients

---

## FILE: routes/api/map.py

### Purpose
Provides geographic map data endpoints, including active issue map markers, cluster boundaries, ward heatmaps, and routing calculations.

---

### FUNCTION: calculate_route()

**What it does**
Handles `POST /api/route` requests from field workers. Validates latitude (-90 to 90) and longitude (-180 to 180) coordinate ranges, then calls `routing_service.get_route()` to compute OSRM road geometry.

**Why this approach was chosen**
- Explicit coordinate range validation (`validate_coordinates()`) prevents passing malformed coordinates (e.g. `lat: 999`) to routing services.

**Line-by-line breakdown**

| Line(s) | Code | What it does | What breaks if you change it |
|:---|:---|:---|:---|
| 35–45 | `if not (-90 <= lat <= 90 and -180 <= lng <= 180): return 400` | Validates latitude and longitude geographic bounds | Omit check → invalid coordinates cause upstream routing service exceptions |

**Connections to other files**
- Calls: `services/routing_service.py → get_route()`

---

## FILE: routes/api/workers.py

### Purpose
Provides REST endpoints for field worker dashboards, including task list retrieval (`GET /api/workers/<id>/tasks`).

---

### FUNCTION: get_worker_tasks_route()

**What it does**
Retrieves assigned task list for a worker. Enforces IDOR security check (`str(g.current_user["_id"]) == worker_id`), querying `services/worker_service.py` to fetch active jobs with calculated proximity distances.

**Why this approach was chosen**
- IDOR check prevents field workers from spying on task queues assigned to other workers.

**Line-by-line breakdown**

| Line(s) | Code | What it does | What breaks if you change it |
|:---|:---|:---|:---|
| 25–28 | `if str(g.current_user["_id"]) != id: return jsonify(...), 403` | IDOR check enforcing worker identity match | Remove check → worker A can view worker B's task list |

**Connections to other files**
- Calls: `services/worker_service.py → get_worker_tasks()`

---

## FILE: utils/validators.py

### Purpose
Provides reusable validation functions for complaint form fields, image file attributes, coordinate boundaries, and state transitions.

---

### FUNCTION: validate_complaint_payload(), validate_coordinates()

**What it does**
- `validate_complaint_payload()`: Rejects complaints with description under 10 characters or invalid category strings.
- `validate_coordinates()`: Verifies numerical latitude (-90 to 90) and longitude (-180 to 180).

**Why this approach was chosen**
- Moving validation logic out of route handlers into modular utility functions ensures consistent validation enforcement across REST API, page controllers, and test runners.

**Line-by-line breakdown**

| Line(s) | Code | What it does | What breaks if you change it |
|:---|:---|:---|:---|
| 12–15 | `if not desc or len(desc.strip()) < 10:` | Rejects short/blank complaint descriptions | Lower limit to 1 → blank or single-character spam complaints reach AI parsing pipeline |

**Connections to other files**
- Called by: `routes/api/issues.py`, `routes/api/map.py`

---

## FILE: utils/geo_utils.py

### Purpose
Provides geographic mathematical calculation helpers, specifically the spherical Haversine distance formula.

---

### FUNCTION: haversine()

**What it does**
Calculates the great-circle distance in kilometers between two geographic points $(\text{lat}_1, \text{lng}_1)$ and $(\text{lat}_2, \text{lng}_2)$ on Earth using spherical trigonometry:
$$a = \sin^2\left(\frac{\Delta\phi}{2}\right) + \cos(\phi_1)\cos(\phi_2)\sin^2\left(\frac{\Delta\lambda}{2}\right)$$
$$c = 2 \cdot \text{atan2}\left(\sqrt{a}, \sqrt{1-a}\right), \quad d = R \cdot c$$

**Why this approach was chosen**
- Standard Euclidean distance ($d = \sqrt{\Delta x^2 + \Delta y^2}$) introduces unacceptable distortion over spherical geographic coordinates. Haversine provides $\approx 99.5\%$ accuracy at municipal scales with $O(1)$ computational cost without external API calls.

**Line-by-line breakdown**

| Line(s) | Code | What it does | What breaks if you change it |
|:---|:---|:---|:---|
| 15–20 | `R = 6371.0` (Earth radius in km) | Sets mean spherical radius of Earth | Use wrong radius → calculated distances between issues/workers inaccurate by miles |

**Connections to other files**
- Called by: `services/duplicate_service.py`, `services/assignment_service.py`, `services/worker_service.py`

---

## FILE: ml/yolo_runner.py

### Purpose
Executes CPU-optimized ONNX inference for local road anomaly detection using fine-tuned YOLOv8n models trained on the RDD2022 dataset.

---

### FUNCTION: run_yolo_inference()

**What it does**
1. Checks for presence of image file and ONNX model file (`ml/models/pothole_yolov8n.onnx`). If missing, returns `{"available": false, "reason": "..."}`.
2. Decodes image using OpenCV, resizes image tensor to $640 \times 640$, normalizes float32 values ($/255.0$), and transposes channels to NCHW format (`[1, 3, 640, 640]`).
3. Runs `onnxruntime.InferenceSession` on CPU.
4. Evaluates output tensor detections against `Config.YOLO_CONFIDENCE_THRESHOLD` (0.40). Returns prediction with `confidence_type: "model"`.

**Why this approach was chosen**
- **YOLOv8n (Nano)**: Designed for ultra-lightweight CPU inference ($\sim 6$ MB ONNX model binary), enabling zero-operating-cost execution without expensive GPU cloud infrastructure.
- **ONNX Runtime**: Running ONNX binaries on CPU is $3\times-5\times$ faster than executing full PyTorch model weights, eliminating heavy PyTorch dependencies in production.
- **RDD2022 Fine-tuning**: Fine-tuned on the Road Damage Dataset 2022, providing high accuracy for pothole and road collapse detection.
- **No Faking**: Returning `available: false` when ONNX runtime or model file is absent guarantees the application never presents hardcoded fake predictions to users.

**Line-by-line breakdown**

| Line(s) | Code | What it does | What breaks if you change it |
|:---|:---|:---|:---|
| 25–35 | `if not os.path.exists(model_path): return {"available": False...}` | Gracefully handles missing model file | Remove check → application throws unhandled FileNotFoundError during complaint submission |
| 58–59 | `img_input = img_resized.transpose(2, 0, 1)[np.newaxis, ...].astype(...) / 255.0` | Preprocesses image to ONNX tensor format | Omit division by 255.0 → unnormalized pixel values ($0-255$) produce garbage model outputs |
| 70–79 | `if max_score >= Config.YOLO_CONFIDENCE_THRESHOLD:` | Evaluates detection box confidence against cutoff | Set cutoff to 0.05 → high false positive rate; set cutoff to 0.99 → misses real potholes |

**Connections to other files**
- Called by: `services/ai_service.py → analyze_complaint_image()`

---

## FILE: tests/

### Purpose
Contains automated unit and integration test suites validating application security, auth, complaints, AI fusion, duplicate clustering, state transitions, worker assignment, and road routing contracts.

---

### TEST SUITES: `test_auth.py`, `test_complaint.py`, `test_ai.py`, `test_duplicate.py`, `test_status_machine.py`, `test_assignment.py`, `test_routing.py`, `test_e2e_verification.py`

**What it does**
- `test_auth.py`: Tests user registration, login, token expiry (401), and RBAC access control (403).
- `test_complaint.py`: Tests complaint creation, short description rejection (400), and non-image rejection (400).
- `test_ai.py`: Validates text confidence types, missing image availability fallback, and text-only fusion.
- `test_duplicate.py`: Validates spatial duplicate detection radius and similarity thresholds.
- `test_status_machine.py`: Validates legal (`in_progress → resolved`) and illegal (`submitted → resolved` 422) status transitions.
- `test_assignment.py`: Tests skill matching, recommendation scoring, and persistent worker status updates.
- `test_routing.py`: Validates Haversine accuracy, coordinate range bounds, and OSRM router fallback.
- `test_e2e_verification.py`: Executes all 39 live end-to-end verification checks across Levels 0 through 9 against running server and MongoDB database.

**Why this approach was chosen**
- Automated test runners ensure regressions are caught instantly during development. Unit tests use Flask test client fixtures to validate endpoint contracts in memory.

---

## 💡 Algorithm Decision Log

| Decision | Alternatives Considered | Why This Was Chosen |
|:---|:---|:---|
| **YOLOv8n ONNX CPU Inference** | PyTorch YOLOv8s/m, Cloud Vision APIs (Google Vision, AWS Rekognition) | Nano (ONNX) is ultra-fast on CPU ($\approx 60$ms); zero operating cost constraint rules out paid cloud APIs; PyTorch runtime is too heavy for lightweight servers. |
| **RDD2022 Dataset Fine-Tuning** | Generic COCO pre-trained weights, ImageNet | COCO lacks road infrastructure defect categories; RDD2022 provides specialized annotated classes for potholes and road damage. |
| **Haversine Geodesic Distance** | Euclidean distance, PostGIS, Google Distance Matrix | Haversine provides $\approx 99.5\%$ spherical accuracy over city-block scales, executes locally in $O(1)$ time with zero external API latency or cost. |
| **OSRM Road Network Routing** | Google Maps Directions API, Mapbox, Valhalla | OSRM is open-source, uses OpenStreetMap data, supports self-hosting, and incurs zero per-query API costs. |
| **MongoDB Document Store** | PostgreSQL + PostGIS, SQLite, MySQL | Municipal complaint documents feature nested, evolving structures (AI analysis dicts, status history arrays, resolution proofs); document model maps naturally without schema migrations. |
| **Stateless JWT Tokens** | Server-side Flask sessions, Redis sessions | JWTs allow stateless authorization across distributed API endpoints and mobile applications without maintaining server-side session stores. |
| **Flask-SocketIO WebSockets** | HTTP long-polling, Server-Sent Events (SSE), Raw WebSockets | Socket.IO natively handles rooms, automatic reconnection, and transport fallbacks, providing seamless real-time notifications to citizens and officers. |
| **TF-IDF / Cosine Text Similarity** | Levenshtein edit distance, Jaccard similarity, BM25 | Cosine similarity on word n-grams captures semantic similarity between paraphrased complaints ("big pothole on road" vs "large crater on street") better than edit distance. |
| **Werkzeug Salted Password Hashing** | Plain SHA-256, MD5 | SHA-256 is designed for computational speed, making it vulnerable to GPU cracking; key-stretching salted hashes add deliberate computational cost to resist dictionary attacks. |

---

*SmartCivic Code Explanation & Architectural Blueprint — Master Reference Document*
