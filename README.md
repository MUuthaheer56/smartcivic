# SmartCivic

> AI-assisted municipal issue-management platform.
> Residents report civic problems. AI understands them. Officers verify and assign.
> Workers navigate and resolve. Residents track the full lifecycle.

SmartCivic is an end-to-end civic issue management platform that automates municipal complaint intake, artificial intelligence classification, spatial deduplication, SLA enforcement, field worker routing, and resolution proof verification. When a resident submits a civic issue with a description, GPS coordinates, and a photo, SmartCivic runs real-time text analysis (via Google Gemini LLM with local rule-based fallback) and local CPU ONNX vision inference (YOLOv8n fine-tuned on RDD2022 road damage datasets) to classify category, issue type, severity, and department. It performs spatial Haversine duplicate scanning within a 200m radius, calculates dynamic priority scores, and assigns target SLA resolution deadlines. On-duty officers review AI recommendations, adjust classifications if necessary, and assign field workers based on skill compatibility, active load, and proximity. Field workers receive real-time updates over WebSockets, compute road-network navigation routes via OSRM, execute repairs, and upload resolution photos, allowing residents to track complete status histories in real time.

**What this README covers**
- How the system works end-to-end across all user roles
- What every file in the repository accomplishes and why it was built that way
- Technical decisions, ML models, and mathematical algorithms used
- Detailed change impact analysis when modifying constants, thresholds, services, or routes

---

## SECTION 2 — System Overview

### 2.1 The Full Lifecycle

1. **Resident submits complaint** (description + photo + GPS coordinates)  
   $\rightarrow$ `POST /api/issues` $\rightarrow$ `services/complaint_service.py → create_complaint()`
2. **Complaint & image validated**  
   $\rightarrow$ `routes/api/issues.py → validate_image_file()` & `utils/validators.py → validate_complaint_payload()`
3. **Image saved to disk**  
   $\rightarrow$ `routes/api/issues.py` $\rightarrow$ `os.rename()` to `static/uploads/issues/issue_<id>_before_<uid>.webp`
4. **Text analysed by AI**  
   $\rightarrow$ `services/ai_service.py → analyze_complaint_text()`
5. **Image analysed by YOLO model**  
   $\rightarrow$ `services/ai_service.py → analyze_complaint_image()` $\rightarrow$ `ml/yolo_runner.py → run_yolo_inference()`
6. **Both predictions fused into one**  
   $\rightarrow$ `services/ai_service.py → fuse_complaint_predictions()`
7. **System checks for duplicate reports**  
   $\rightarrow$ `services/duplicate_service.py → detect_duplicate()` & `services/ai_service.py → detect_duplicates()`
8. **Priority calculated**  
   $\rightarrow$ `services/priority_service.py → calculate_priority()`
9. **SLA deadline set**  
   $\rightarrow$ `services/sla_service.py → assign_sla()`
10. **Issue saved to MongoDB**  
    $\rightarrow$ `services/complaint_service.py` $\rightarrow$ `db.issues.insert_one()`
11. **Officer logs in and reviews complaint queue**  
    $\rightarrow$ `GET /api/issues` $\rightarrow$ `routes/api/issues.py → list_issues()`
12. **Officer overrides AI classification if needed**  
    $\rightarrow$ `PATCH /api/issues/<id>/classification` $\rightarrow$ `routes/api/issues.py → update_issue_classification()`
13. **Officer gets worker recommendations**  
    $\rightarrow$ `GET /api/issues/<id>/recommendations` $\rightarrow$ `services/assignment_service.py → recommend_workers()`
14. **Officer assigns a worker**  
    $\rightarrow$ `POST /api/issues/<id>/assignment` $\rightarrow$ `services/assignment_service.py → assign_worker()`
15. **Worker logs in and sees assigned task**  
    $\rightarrow$ `GET /api/workers/<id>/tasks` $\rightarrow$ `services/worker_service.py → get_worker_tasks()`
16. **Worker requests road-network route to issue**  
    $\rightarrow$ `POST /api/route` $\rightarrow$ `services/routing_service.py → get_route()`
17. **Worker resolves issue and uploads resolution proof**  
    $\rightarrow$ `POST /api/issues/<id>/resolution` $\rightarrow$ `routes/api/issues.py → submit_resolution_proof()`
18. **Resident tracks full status history timeline**  
    $\rightarrow$ `GET /api/issues/<id>` $\rightarrow$ `routes/api/issues.py → get_issue()`

---

### 2.2 Three Roles

| Role | What they can do | What they cannot do |
|:---|:---|:---|
| **Resident** | Submit complaints, view own submitted issues, track status history timeline, confirm community issues, submit feedback ratings on closed issues | View other residents' complaints, assign workers, override AI classifications, alter system SLAs |
| **Officer** | Review all complaints across assigned ward, override AI categories/severities, view worker recommendation scores, assign/unassign workers, view city audit logs & analytics | Submit complaints as a citizen, bypass worker resolution proof requirements |
| **Worker** | View assigned active tasks with Haversine distances, request OSRM road geometry routes, transition task status (`en_route`, `in_progress`, `resolved`), upload resolution proof photos | View task queues assigned to other workers, self-assign unallocated complaints, modify initial issue locations |

---

### 2.3 Technology Stack

| Technology | Version | Role in SmartCivic | Why chosen over alternatives |
|:---|:---|:---|:---|
| **Flask** | `3.0.0` | Web Application WSGI framework | Lightweight, minimal overhead, flexible application factory design, seamlessly integrates PyMongo and Socket.IO without heavy ORM layers. |
| **MongoDB** | `4.6.1` (PyMongo) | Primary NoSQL document database | Municipal complaint documents feature nested, evolving fields (AI dicts, GeoJSON points, status history arrays, resolution proofs); document store handles variable data shapes without rigid SQL schema migrations. |
| **Flask-SocketIO** | `5.3.6` | Real-time WebSocket notifications | Handles WebSocket rooms, automatic client reconnection, and event emissions cleanly under the `/civic` namespace without polling overhead. |
| **PyJWT** | `2.8.0` | Stateless authentication tokens | Enables stateless authentication across web browsers and API clients via signed HS256 JWT tokens (`access_token`, `refresh_token`). |
| **YOLOv8n (ONNX)** | `onnxruntime` | Local CPU road defect image detection | Nano variant ($\sim 6$ MB binary) is optimized for ultra-fast single-pass CPU inference ($\sim 60$ms); ONNX Runtime removes PyTorch dependency; zero operating cost. |
| **OSRM** | Open Source | Road-network geometry navigation | Open-source driving router using OpenStreetMap data; calculates real street-network geometries; zero API subscription costs. |
| **Gemini API** | `google-generativeai 0.7.0` | Natural language text parsing & translation | Large language model accurately classifies free-text complaint descriptions and translates Indic languages far better than rigid regex matchers. |
| **Werkzeug Passwords** | Built-in | Password security hashing | Implements salted `scrypt` / `pbkdf2:sha256` key-stretching algorithms; deliberately slow to resist GPU dictionary cracking, unlike plain SHA-256. |
| **Flask-Limiter** | `4.1.1` | Security rate limiting | Prevents brute-force credential stuffing and Denial-of-Service API flooding via in-memory IP rate limiting. |

---

## SECTION 3 — File and Folder Structure

```
code 1/
│
├── app.py
│   What: Core Flask application factory. Instantiates app, PyMongo handle, Socket.IO, Limiter, security headers, blueprints, and APScheduler background jobs.
│   If deleted: Application cannot start. Nothing imports database or extension singletons.
│
├── config.py
│   What: Central application configuration. Defines environment secrets, SLA hours, duplicate thresholds, ML paths, token lifetimes, and department mappings.
│   If deleted: All services and route blueprints crash on launch due to missing `Config` attributes.
│
├── extensions.py
│   What: Holds unattached Flask extension instances (`db`, `jwt`, `socketio`, `limiter`) to avoid circular imports.
│   If deleted: Circular import errors occur between `app.py` and route modules during blueprint initialization.
│
├── run.py
│   What: Application entrypoint runner script. Spawns WSGI server on port 5000 and starts background schedulers.
│   If deleted: Development dev server command `python run.py` fails.
│
├── test_app_plus.py
│   What: Comprehensive unit test runner validating database indexes, authentication, complaints, AI fusion, SLAs, and security controls.
│   If deleted: Automated regression testing suite lost.
│
├── test_e2e_verification.py
│   What: End-to-end verification script executing all 39 live system checks across Levels 0 through 9 against active Flask server and MongoDB.
│   If deleted: Live application end-to-end lifecycle verification test suite lost.
│
├── test_real_vision.py
│   What: Verification test script executing real ONNX/Gemini vision inference against local test image fixtures.
│   If deleted: Image analysis validation script missing.
│
├── requirements.txt
│   What: Lists pinned Python package dependencies and version requirements.
│   If deleted: Dependency installation via `pip install -r requirements.txt` fails.
│
├── ml/
│   ├── __init__.py
│   │   What: Package initialization for ML module.
│   │   If deleted: Module imports from `ml` fail.
│   ├── yolo_runner.py
│   │   What: ONNX YOLOv8 CPU inference runner. Preprocesses images to 640x640 tensors, executes ONNX Runtime, applies confidence cutoffs, and returns defect classifications.
│   │   If deleted: Image defect detection crashes; `ai_service.analyze_complaint_image()` fails.
│   └── models/
│       └── pothole_yolov8n.onnx
│           What: Fine-tuned YOLOv8n ONNX model binary trained on RDD2022 road damage dataset.
│           If deleted: Vision inference falls back to `available: false` with model missing reasoning.
│
├── models/
│   ├── __init__.py
│   │   What: Package initialization for data models.
│   │   If deleted: Imports from `models` fail.
│   ├── user.py
│   │   What: User document builder `create_user_doc()` and Marshmallow user schemas (`resident`, `officer`, `worker`).
│   │   If deleted: Registration route fails to construct structured user documents in MongoDB.
│   ├── issue.py
│   │   What: Issue document builder `create_issue_doc()`, system enum constants (`STATUSES`, `CATEGORIES`), and Marshmallow issue schemas.
│   │   If deleted: Complaint creation pipeline cannot build valid GeoJSON issue documents.
│   ├── assignment.py
│   │   What: Assignment document builder `create_assignment_doc()`.
│   │   If deleted: Worker assignment service fails when creating assignment records.
│   ├── audit_log.py
│   │   What: Audit log document builder `create_audit_log_doc()`.
│   │   If deleted: Audit logging fails across issue updates and administrative actions.
│   ├── cluster.py
│   │   What: Duplicate cluster document builder `create_cluster_doc()`.
│   │   If deleted: Spatial duplicate cluster generation fails.
│   ├── notification.py
│   │   What: Notification document builder `create_notification_doc()`.
│   │   If deleted: Persistent notification records cannot be created.
│   ├── sla.py
│   │   What: SLA document schema definitions.
│   │   If deleted: Structured SLA metadata helpers unavailable.
│   ├── ai_evaluation.py
│   │   What: AI evaluation document builder for tracking human vs AI classification accuracy.
│   │   If deleted: AI accuracy evaluation recording fails.
│   └── infrastructure.py
│       What: Infrastructure asset segment document builders.
│       If deleted: Asset linkage functionality unavailable.
│
├── services/
│   ├── __init__.py
│   │   What: Package initialization for services.
│   │   If deleted: Service package imports fail.
│   ├── auth_service.py
│   │   What: User password hashing, JWT token issuance, token verification, and role-based decorator authorization (`require_auth`, `require_role`).
│   │   If deleted: Application authentication and RBAC authorization fail completely.
│   ├── complaint_service.py
│   │   What: Central complaint orchestrator (`create_complaint`, `update_status`). Manages complaint creation, translation, AI fusion, duplicate checks, SLA setup, status transitions, and audit logs.
│   │   If deleted: Core complaint submission, review, and resolution status workflows break.
│   ├── ai_service.py
│   │   What: AI analysis engine (`analyze_text`, `analyze_image`, `fuse_predictions`). Integrates Gemini LLM, YOLO ONNX runner, heuristic fallbacks, and prediction fusion.
│   │   If deleted: AI text/image prediction and prediction fusion break.
│   ├── duplicate_service.py
│   │   What: Duplicate detection engine (`detect_duplicate`). Calculates Haversine distance and text similarity to flag duplicate reports within 200m.
│   │   If deleted: Duplicate reports create redundant open complaints for the same physical pothole.
│   ├── priority_service.py
│   │   What: Priority calculation engine (`calculate_priority`). Computes numerical priority scores based on severity, confirmations, age, and emergency flags.
│   │   If deleted: Issue queue ordering in officer/worker dashboards reverts to unprioritized lists.
│   ├── sla_service.py
│   │   What: SLA manager (`assign_sla`, `check_sla_status`). Assigns resolution deadlines by severity and flags breaches during periodic sweeps.
│   │   If deleted: SLA target deadlines not set; breach detection sweeps fail.
│   ├── assignment_service.py
│   │   What: Worker assignment engine (`recommend_workers`, `assign_worker`). Matches worker skills, calculates proximity, ranks workers, and updates assignment states.
│   │   If deleted: Worker recommendation and assignment features break.
│   ├── routing_service.py / route_service.py
│   │   What: OSRM driving route navigation service (`get_route`, `haversine`). Fetches road-network polyline geometries and step-by-step travel times.
│   │   If deleted: Worker navigation route calculation fails.
│   ├── worker_service.py
│   │   What: Worker task query service (`get_worker_tasks`). Retrieves assigned tasks with calculated distances for worker dashboard.
│   │   If deleted: Field worker task dashboard fails to load active jobs.
│   ├── notification_service.py
│   │   What: Socket.IO WebSocket push notification manager (`send`). Emits events to specific user, ward, or officer WebSocket rooms under `/civic`.
│   │   If deleted: Real-time status push updates fail.
│   ├── briefing_service.py
│   │   What: Officer daily briefing synthesizer using Gemini LLM.
│   │   If deleted: Automated daily officer briefing generation fails.
│   ├── report_service.py
│   │   What: Automated weekly intelligence PDF report generator.
│   │   If deleted: Weekly PDF report generation fails.
│   ├── verification_service.py
│   │   What: Resolution proof verification engine comparing before/after repair photos.
│   │   If deleted: Automated resolution photo comparison fails.
│   ├── civicpulse_service.py
│   │   What: Predictive analytics engine calculating ward failure likelihood scores.
│   │   If deleted: Predictive ward risk analysis features fail.
│   ├── infrastructure_service.py
│   │   What: Asset segment linking service associating complaints with road segments.
│   │   If deleted: Infrastructure asset linkage features fail.
│   └── logger_service.py
│       What: Security and API audit logging service.
│       If deleted: Rotating JSON security log writing fails.
│
├── routes/
│   ├── __init__.py
│   │   What: Package initialization for routes.
│   │   If deleted: Route imports fail.
│   ├── auth.py
│   │   What: Authentication routes (`/api/auth/register`, `/api/auth/login`, `/api/auth/refresh`, `/api/auth/logout`, `/api/auth/me`).
│   │   If deleted: User registration, login, and session management endpoints fail.
│   ├── citizen.py
│   │   What: Page controller for resident frontend views.
│   │   If deleted: Resident dashboard pages fail to render.
│   ├── officer.py
│   │   What: Page controller for officer frontend views.
│   │   If deleted: Officer dashboard pages fail to render.
│   ├── worker.py
│   │   What: Page controller for worker frontend views.
│   │   If deleted: Worker dashboard pages fail to render.
│   └── api/
│       ├── issues.py
│       │   What: Primary REST API blueprint for complaints (`/api/issues`). Implements submit, fetch, filter list, review, classification override, assignment, resolution proof, confirm, feedback, and audit endpoints.
│       │   If deleted: Core complaint management REST API endpoints return 404.
│       ├── map.py
│       │   What: Geographic map data & routing endpoints (`/api/map/markers`, `/api/route`).
│       │   If deleted: Map markers and route navigation endpoints return 404.
│       ├── workers.py
│       │   What: Worker task REST endpoints (`/api/workers/<id>/tasks`).
│       │   If deleted: Worker dashboard task fetching returns 404.
│       ├── analytics.py
│       │   What: Municipal analytics dashboard endpoints (`/api/analytics/*`).
│       │   If deleted: Analytics charts and summary APIs fail.
│       ├── civicpulse.py
│       │   What: Predictive analytics endpoints (`/api/civicpulse/*`).
│       │   If deleted: Predictive risk score APIs fail.
│       ├── notifications.py
│       │   What: User notification listing endpoints (`/api/notifications`).
│       │   If deleted: User notification inbox APIs return 404.
│       └── simulation.py
│           What: Civic event simulation test endpoints.
│           If deleted: Simulation APIs fail.
│
├── utils/
│   ├── __init__.py
│   │   What: Re-exports serialization helpers (`serialize`, `parse_object_id`).
│   │   If deleted: Document serialization across blueprints fails.
│   ├── validators.py
│   │   What: Input validation functions (`validate_complaint_payload`, `validate_coordinates`).
│   │   If deleted: Request validation helpers unavailable.
│   ├── geo_utils.py
│   │   What: Standalone spherical Haversine calculation module.
│   │   If deleted: Standalone geographic calculation utilities fail.
│   └── image_utils.py
│       What: Uploaded image persistence and URL generation helpers.
│       If deleted: Image processing utility functions break.
│
└── tests/
    ├── test_auth.py
    │   What: Unit tests for authentication, login lockouts, JWT refresh, and RBAC authorization.
    │   If deleted: Auth unit testing lost.
    ├── test_complaint.py
    │   What: Unit tests for complaint creation, length validation, and image upload checks.
    │   If deleted: Complaint submission unit testing lost.
    ├── test_ai.py
    │   What: Unit tests for AI text analysis, ONNX availability handling, and prediction fusion.
    │   If deleted: AI pipeline unit testing lost.
    ├── test_duplicate.py
    │   What: Unit tests for spatial duplicate detection radius and score boundaries.
    │   If deleted: Duplicate clustering unit testing lost.
    ├── test_status_machine.py
    │   What: Unit tests validating legal and illegal status transitions.
    │   If deleted: State machine unit testing lost.
    ├── test_assignment.py
    │   What: Unit tests for worker skill matching, recommendation scoring, and assignment.
    │   If deleted: Assignment unit testing lost.
    └── test_routing.py
        What: Unit tests for Haversine accuracy, ETA calculations, and OSRM fallback handling.
        If deleted: Routing unit testing lost.
```

---

## SECTION 4 — Every Configuration Constant Explained

#### `DUPLICATE_RADIUS_METERS = 200`

**What it controls:**  
The maximum distance in meters within which two complaints of the same category are evaluated as potential duplicates.

**Why 200:**  
200 meters represents approximately one city block. In municipal planning, reports of the same category (e.g. pothole or water leak) within 200 meters are very likely referring to the same physical asset failure, whereas reports >200 meters apart represent separate infrastructure issues.

**Which files read this:**  
`services/duplicate_service.py → detect_duplicate()`, `services/ai_service.py → detect_duplicates()`, `services/complaint_service.py → create_complaint()`

**What happens if you change it:**

| New value | Effect |
|:---|:---|
| `50` | Only complaints on the exact same corner are clustered. Reports 100m away create duplicate jobs for officers. |
| `500` | Complaints across 5 blocks get merged. Distinct potholes in the same neighborhood get falsely suppressed. |
| `0` | Spatial duplicate detection is disabled. Every complaint creates a separate operational ticket. |
| *Removed* | `detect_duplicate()` raises `AttributeError` / `NameError` during complaint submission. |

---

#### `DUPLICATE_THRESHOLD = 0.85`

**What it controls:**  
The combined similarity score threshold ($\ge 0.85$) required to automatically flag a new complaint as a duplicate (`status: "duplicate"`).

**Why 0.85:**  
0.85 requires both close geographic proximity ($\ge 70\%$ weight) and high textual/type similarity ($\ge 30\%$ weight), preventing false positives while catching true duplicate reports.

**Which files read this:**  
`services/duplicate_service.py`, `services/complaint_service.py`

**What happens if you change it:**

| New value | Effect |
|:---|:---|
| `0.40` | Over-clustering. Unrelated issues (e.g. street light outage vs pothole near same corner) get suppressed as duplicates. |
| `0.99` | Under-clustering. Slightly rephrased reports of the exact same pothole fail to cluster, creating duplicate work tickets. |

---

#### `SLA_HOURS = {"critical": 4, "high": 24, "medium": 72, "low": 168}`

**What it controls:**  
Target resolution time window in hours for each complaint severity level.

**Why these values:**  
Standard municipal SLA guidelines: 4 hours for emergency/critical hazards (e.g. road collapse), 24 hours for urgent high-risk issues, 72 hours (3 days) for medium issues (standard pothole), 168 hours (7 days) for low-priority maintenance.

**Which files read this:**  
`services/sla_service.py → assign_sla()`, `routes/api/issues.py → update_issue_classification()`

**What happens if you change it:**

| New value | Effect |
|:---|:---|
| `critical: 1` | Unrealistic 1-hour resolution window; leads to constant false SLA breach alerts for emergency crews. |
| `critical: 72` | Critical safety hazards remain un-breached for 3 days, delaying urgent response. |
| *Key removed* | SLA deadline assignment raises `KeyError` during complaint creation. |

---

#### `MAX_UPLOAD_SIZE = 10 * 1024 * 1024` (10MB) / `MAX_IMAGE_BYTES = 10 * 1024 * 1024`

**What it controls:**  
Maximum allowable file size in bytes for uploaded complaint and resolution proof photos.

**Why 10MB:**  
Accommodates modern smartphone camera resolutions (typically 3MB–8MB JPEGs) while capping server memory consumption and preventing disk exhaustion attacks.

**Which files read this:**  
`routes/api/issues.py → validate_image_file()`, `utils/validators.py`

**What happens if you change it:**

| New value | Effect |
|:---|:---|
| `1MB` | High-resolution mobile phone photos rejected with 400 validation error. |
| `100MB` | Vulnerability to memory exhaustion and Denial-of-Service storage attacks. |

---

#### `YOLO_CONFIDENCE_THRESHOLD = 0.40`

**What it controls:**  
Minimum confidence score cutoff ($0.40$) for accepting object detection bounding boxes from ONNX YOLO inference.

**Why 0.40:**  
Filters out background noise, shadows, and road surface texture variations while reliably retaining true pothole and crack detections.

**Which files read this:**  
`ml/yolo_runner.py → run_yolo_inference()`

**What happens if you change it:**

| New value | Effect |
|:---|:---|
| `0.05` | Severe false positives. Shadows and normal asphalt textures classified as critical road damage. |
| `0.90` | Severe false negatives. Misses valid potholes and cracks with moderate visual confidence ($0.50-0.80$). |

---

#### `YOLO_MODEL_PATH = "ml/models/pothole_yolov8n.onnx"`

**What it controls:**  
File system path to the fine-tuned YOLOv8n ONNX model binary.

**Which files read this:**  
`ml/yolo_runner.py`

**What happens if you change it:**  
If changed to a non-existent path, `run_yolo_inference()` returns `{"available": false, "reason": "Model file missing"}` and vision analysis falls back gracefully without crashing.

---

#### `ROUTING_ENGINE_URL = "http://router.project-osrm.org/route/v1/driving/"` / `ROUTING_TIMEOUT_SECONDS = 5`

**What it controls:**  
Base URL for public/self-hosted OSRM router and maximum HTTP socket timeout (5 seconds).

**Which files read this:**  
`services/routing_service.py → get_route()`, `services/route_service.py`

**What happens if you change it:**  
If set to an invalid URL or if OSRM is offline, `get_route()` catches the request timeout and returns `{"available": false, "reason": "routing_service_unavailable"}` cleanly.

---

#### `JWT_ACCESS_EXPIRES = timedelta(minutes=30)` / `JWT_REFRESH_EXPIRES = timedelta(days=7)`

**What it controls:**  
Validity durations for short-lived access tokens (30 mins) and long-lived refresh tokens (7 days).

**Which files read this:**  
`services/auth_service.py → generate_tokens()`, `routes/auth.py`

**What happens if you change it:**  
If access token duration is set to 2 seconds, users are forced to refresh sessions constantly. If set to 1 year, stolen access tokens remain valid indefinitely.

---

#### `CATEGORY_TO_DEPARTMENT` & `ISSUE_TYPE_TO_SKILLS`

**What it controls:**  
Dictionaries mapping complaint categories to municipal departments (`road → roads`, `water → water_supply`) and issue types to worker skills (`pothole → ["road_repair", "pothole_repair"]`).

**Which files read this:**  
`services/ai_service.py`, `services/assignment_service.py`

**What happens if you change it:**  
Modifying skill mappings alters which workers are selected by `recommend_workers()`.

---

## SECTION 5 — Every Service Explained

### 5.1 `services/ai_service.py`

**Role in the system:**  
Serves as the AI analysis hub. Parses natural-language complaint text via Gemini LLM (or keyword heuristics when offline/rate-limited), triggers local CPU ONNX vision inference via `ml/yolo_runner.py`, and fuses text and visual findings into a unified prediction object.

##### `analyze_complaint_text(description: str) -> dict`

**What it does:**  
Sends text to Gemini LLM (or keyword fallback) to extract category, issue type, severity, and department, returning `confidence_type: "model"` or `"heuristic"`.

**Why this approach:**  
Natural language civic complaint descriptions vary greatly ("giant pit in asphalt", "rasta kharab hai"). LLMs handle paraphrases and Indic multilingual phrasing effectively. The heuristic fallback ensures zero-downtime complaint intake when Gemini API quotas are exceeded.

**Line-by-line breakdown:**

| Line(s) | Code | What it does | What changes if modified |
|:---|:---|:---|:---|
| 110–125 | `try: response = _generate_content_with_model_fallback(...)` | Executes Gemini LLM text classification prompt | Omit fallback $\rightarrow$ API rate-limits take down complaint submission entirely |
| 135–140 | `parsed["confidence_type"] = "model"` | Labels output as genuine model inference | Change to "heuristic" $\rightarrow$ officer dashboard flags valid AI predictions as rule fallbacks |
| 145–165 | `except Exception: return rule_based_fallback(description)` | Executes keyword heuristic fallback when Gemini fails | Remove fallback $\rightarrow$ complaints fail with 500 server error when Gemini is offline |

**Connections:**  
- Called by: `services/complaint_service.py → create_complaint()`  
- Calls: Google Gemini API, `ml/yolo_runner.py`  
- Output consumed by: `fuse_complaint_predictions()`

---

##### `analyze_complaint_image(image_path: str) -> dict`

**What it does:**  
Invokes `ml/yolo_runner.py` to run local CPU ONNX inference on the image. If model file or runtime is missing, returns `available: false` with reasoning.

**Why YOLOv8n specifically:**  
YOLO (You Only Look Once) is a single-pass object detection network ($O(1)$ pass per image). The nano variant (YOLOv8n) is chosen for zero-operating-cost CPU execution ($\sim 60$ms per image). ONNX Runtime provides a lightweight CPU inference footprint without requiring PyTorch. RDD2022 dataset fine-tuning supplies specialized detection classes for road damage.

**Why `available: false` must never become a fake prediction:**  
Returning a fake prediction when the vision model is offline deceives officers into believing an unanalyzed image was verified by AI, compromising operational integrity.

---

##### `fuse_complaint_predictions(text_res, img_res) -> dict`

**What it does:**  
Combines text and image predictions. When high-confidence image detection is available, visual evidence overrides subjective resident text phrasing.

**Why image is weighted higher than text:**  
Resident descriptions are subjective ("huge crater" vs "small bump"). Visual detection measures pixel area against calibrated defect classes, producing objective severity assessments.

---

### 5.2 `services/complaint_service.py`

**Role in the system:**  
The central application workflow orchestrator. Manages complaint creation, translation, AI fusion, duplicate checks, SLA setup, status transitions, and audit logging.

##### `create_complaint()`, `update_status()`

**What it does:**  
- `create_complaint()`: Executes full intake pipeline: Text translation $\rightarrow$ Document build $\rightarrow$ AI analysis $\rightarrow$ Duplicate scan $\rightarrow$ SLA calculation $\rightarrow$ MongoDB save $\rightarrow$ Socket.IO notification.
- `update_status()`: Enforces state machine transitions against `LEGAL_TRANSITIONS` dict (`submitted → under_review → verified → assigned → en_route → in_progress → resolved → closed`).

---

### 5.3 `services/duplicate_service.py`

**Role in the system:**  
Computes spatial Haversine distance and text similarity to detect and flag duplicate complaints within 200m.

---

### 5.4 `services/priority_service.py`

**Role in the system:**  
Calculates dynamic numerical priority scores (`priority_score`) combining base severity, community confirmations, age decay, and emergency flags.

---

### 5.5 `services/sla_service.py`

**Role in the system:**  
Calculates SLA resolution target deadlines and checks breach status during automated background sweeps.

---

### 5.6 `services/assignment_service.py`

**Role in the system:**  
Ranks available field workers by skill match, workload, and Haversine distance (`recommend_workers()`), and executes persistent 4-part state updates upon worker assignment (`assign_worker()`).

---

### 5.7 `services/routing_service.py` / `route_service.py`

**Role in the system:**  
Fetches real road-network driving polyline geometry from OSRM for field worker navigation.

---

### 5.8 `services/worker_service.py`

**Role in the system:**  
Queries active tasks assigned to specific field workers (`get_worker_tasks()`) with computed proximity distances.

---

### 5.9 `services/notification_service.py`

**Role in the system:**  
Emits real-time Socket.IO WebSocket push events to targeted user rooms (`user_<id>`, `ward_<name>`, `role_officer`) under `/civic`.

---

## SECTION 6 — Every Route Explained

| Method | Path | Role required | Service called | What it returns | What breaks if role check is removed |
|:---|:---|:---|:---|:---|:---|
| `POST` | `/api/auth/register` | Public | `models/user.py → create_user_doc()` | 201 + User ID | Staff roles (`officer`, `worker`) registered without Admin Invite Code check. |
| `POST` | `/api/auth/login` | Public | `services/auth_service.py → generate_tokens()` | 200 + JWT tokens + HttpOnly cookies | Authentication bypass. |
| `POST` | `/api/issues` | Resident | `complaint_service.create_complaint()` | 201 + Full issue document | Anonymous users can flood database with fake complaints. |
| `GET` | `/api/issues/<id>` | Resident / Officer | `complaint_service.get_complaint()` | 200 + Full issue detail + status history | Resident can read other citizens' private complaints (IDOR flaw). |
| `GET` | `/api/issues` | Resident / Officer | `routes/api/issues.py → list_issues()` | 200 + Filtered issues list | Resident can view full citywide issue database. |
| `PATCH` | `/api/issues/<id>/status` | Authenticated | `complaint_service.update_status()` | 200 + Updated issue | Unauthenticated users can alter complaint lifecycle states. |
| `PATCH` | `/api/issues/<id>/classification` | Officer | `update_issue_classification()` | 200 + Updated classification & SLA | Citizens/Workers can override AI predictions and severity levels. |
| `GET` | `/api/issues/<id>/recommendations` | Officer | `assignment_service.recommend_workers()` | 200 + Ranked worker list | Public users can inspect field worker locations and workloads. |
| `POST` | `/api/issues/<id>/assignment` | Officer | `assignment_service.assign_worker()` | 200 + Success message | Workers or residents can assign arbitrary workers to complaints. |
| `GET` | `/api/workers/<id>/tasks` | Worker | `worker_service.get_worker_tasks()` | 200 + Assigned tasks list | Worker A can view Worker B's assigned task queue (IDOR flaw). |
| `POST` | `/api/route` | Worker | `routing_service.get_route()` | 200 + OSRM road geometry | Public API abuse for arbitrary routing calculations. |
| `POST` | `/api/issues/<id>/resolution` | Worker | `routes/api/issues.py → submit_resolution_proof()` | 200 + Resolution proof data | Unauthorized users can resolve complaints without submitting proof photos. |

---

### IDOR Protection in Routes

**What IDOR means here:**  
Insecure Direct Object Reference (IDOR) occurs when an endpoint accepts a database identifier (e.g. `GET /api/issues/SC-2026-000456`) without verifying that the requesting user owns or is authorized to view that object.

**How SmartCivic enforces IDOR checks:**  
In `routes/api/issues.py` (`get_issue`):
```python
user_role = g.current_user.get("role")
if user_role in ["resident", "citizen"] and str(issue.get("citizen_id")) != str(g.current_user["_id"]):
    return jsonify({"success": False, "error": {"code": "FORBIDDEN", "message": "Access restricted to your own issues."}}), 403
```
And in `routes/api/workers.py` (`get_worker_tasks_route`):
```python
if str(g.current_user["_id"]) != id:
    return jsonify({"success": False, "error": {"code": "FORBIDDEN", "message": "Access denied."}}), 403
```
Removing these checks allows any authenticated resident to view all complaints across the city or inspect other workers' task queues.

---

## SECTION 7 — Data Models Explained

### 7.1 `issues` Collection Schema

| Field | Type | What it stores | What breaks if removed | Who writes it | Who reads it |
|:---|:---|:---|:---|:---|:---|
| `_id` | ObjectId | Unique MongoDB document identifier | Document lookup by primary key fails | MongoDB | All services & routes |
| `issue_id` | String | Formatted ID (`SC-2026-XXXXXX`) | Human-readable issue reference fails | `complaint_service` | Dashboards & REST API |
| `citizen_id` | ObjectId | User ID of reporting resident | Resident ownership checks and IDOR validation fail | `complaint_service` | `routes/api/issues.py` |
| `status` | String | Lifecycle state (`submitted`, `assigned`, `resolved`) | State machine transition validation breaks | `update_status()` | Dashboards & services |
| `ai_prediction` | Object | Baseline AI prediction (untouched) | AI evaluation auditing breaks on officer overrides | `ai_service` | Officer review view |
| `operational_classification` | Object | Officer-confirmed category/severity | System uses unreviewed AI predictions directly | `update_issue_classification()` | `assignment_service` |
| `location` | Object | GeoJSON Point (`{"type": "Point", "coordinates": [lng, lat]}`) | 2dsphere index fails; `$near` proximity queries crash | `models/issue.py` | `duplicate_service`, `map.py` |
| `sla` | Object | Target deadline and breach flag | SLA breach monitoring sweeps fail | `sla_service` | Schedulers & dashboards |
| `assignment` | Object | Worker ID, assigned timestamp, officer ID | Worker task query fails to find assigned worker | `assign_worker()` | `worker_service` |
| `status_history` | Array | Log of all status transitions with timestamps | Resident tracking timeline breaks | `update_status()` | Resident tracking UI |

---

## SECTION 8 — Status State Machine

### Allowed Transitions (`LEGAL_TRANSITIONS`)

| From State | Allowed Next States | Triggered By | Route / Service |
|:---|:---|:---|:---|
| `submitted` | `under_review`, `ai_reviewed`, `officer_reviewed`, `assigned`, `rejected` | Officer | `PATCH /api/issues/<id>/status` |
| `under_review` | `verified`, `officer_reviewed`, `assigned`, `rejected` | Officer | `PATCH /api/issues/<id>/status` |
| `verified` | `assigned`, `rejected` | Officer | `POST /api/issues/<id>/assignment` |
| `assigned` | `en_route`, `work_started`, `in_progress` | Worker | `PATCH /api/issues/<id>/status` |
| `en_route` | `work_started`, `in_progress`, `work_completed`, `resolved` | Worker | `PATCH /api/issues/<id>/status` |
| `in_progress` | `work_completed`, `resolved` | Worker | `POST /api/issues/<id>/resolution` |
| `resolved` | `officer_verified`, `closed`, `reopened` | Officer / Resident | Verification routes |
| `duplicate` | `under_review`, `officer_reviewed`, `rejected` | Officer | Officer override routes |

**What `update_status()` validation accomplishes:**  
Checks requested new status against `LEGAL_TRANSITIONS[current_status]`. If illegal, raises `ValueError`, returning HTTP 422.

**What happens if check is removed:**  
State machine corruption. Workers could mark unassigned complaints as `resolved`, or residents could mark submitted complaints as `closed` without repair proof.

---

## SECTION 9 — ML Components Explained

### 9.1 YOLOv8n ONNX Architecture
- **Single-Pass Detection**: YOLO processes the entire image in one forward pass, predicting bounding boxes and class probabilities simultaneously ($O(1)$ complexity vs $O(N)$ region proposal networks).
- **CPU Optimization via ONNX**: Running ONNX binaries on CPU eliminates heavy PyTorch runtime dependencies, providing $\approx 60$ms inference times.
- **RDD2022 Fine-Tuning**: Fine-tuned on the Road Damage Dataset 2022 covering Indian road surface defect textures across 6 classes (longitudinal cracks, transverse cracks, alligator cracks, potholes, repair patches, road collapse).

### 9.2 Haversine Geodesic Distance
- Calculates great-circle distance over Earth's curved surface:
  $$d = 2R \cdot \text{atan2}\left(\sqrt{a}, \sqrt{1-a}\right)$$
- Euclidean distance ($\sqrt{\Delta x^2 + \Delta y^2}$) introduces significant distortion over geographic coordinates. Haversine provides $\approx 99.5\%$ accuracy at city-block scale without external API calls.

### 9.3 Cosine Text Similarity
- Measures vector angle between word n-gram TF-IDF representations:
  $$\text{Cosine Similarity} = \frac{\mathbf{A} \cdot \mathbf{B}}{\|\mathbf{A}\| \|\mathbf{B}\|}$$
- Handles paraphrased descriptions ("crater on highway" vs "deep pothole on main road") far better than Levenshtein character edit distance.

### 9.4 OSRM Road Geometry
- Fetches actual driving route geometries along the OpenStreetMap street network rather than straight lines. Returning `available: false` during OSRM outages guarantees workers are not navigated along unsafe straight lines passing through physical obstacles.

---

## SECTION 10 — Algorithm Decision Log

| Technical Decision | Selected Approach | Alternatives Considered | Why Chosen | Downstream Impact if Switched |
|:---|:---|:---|:---|:---|
| **Vision Model** | YOLOv8n ONNX | Cloud Vision APIs, Faster R-CNN, PyTorch weights | Ultra-fast single-pass CPU inference ($\sim 60$ms); zero API cost. | Cloud APIs: high operational cost. PyTorch: heavy runtime dependencies. |
| **Distance Formula** | Haversine Formula | Euclidean Distance, PostGIS, Google Matrix API | $O(1)$ local spherical accuracy at city-block scale without external calls. | Euclidean: spatial distortion. Google API: high latency & cost. |
| **Routing Engine** | OSRM Driving Router | Google Maps Directions, Mapbox | Free, self-hostable, uses OpenStreetMap, zero cost. | Paid APIs: per-request cost accumulation. |
| **Database** | MongoDB | PostgreSQL + PostGIS, SQLite | Flexible document schema handles evolving AI/JSON fields without migrations. | SQL: rigid schema migrations required for every AI model change. |
| **Auth Tokens** | Stateless JWT | Flask Sessions, Redis Sessions | Works across API and mobile clients without server-side session storage. | Sessions: requires centralized Redis session store. |
| **Real-time Push** | Socket.IO WebSockets | HTTP Polling, Server-Sent Events | Room-based targeted emissions (`ward_*`, `user_*`) without polling load. | Polling: server CPU & network saturation. |
| **Password Hash** | Salted Scrypt / PBKDF2 | Plain SHA-256, MD5 | Key-stretching resists GPU dictionary cracking. | SHA-256: vulnerable to instant rainbow-table cracking. |

---

## SECTION 11 — Change Impact Matrix

| Component Modified | `complaint_service` | `ai_service` | `duplicate_service` | `assignment_service` | `routing_service` | `issue_routes` | `worker_dashboard` | `resident_dashboard` |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| `Config.DUPLICATE_RADIUS_METERS` | No effect | No effect | **Behavioural** | No effect | No effect | No effect | No effect | No effect |
| `ai_service.fuse_predictions()` keys | **Breaking** | — | No effect | **Breaking** | No effect | **Breaking** | No effect | No effect |
| `LEGAL_TRANSITIONS` dict | No effect | No effect | No effect | **Breaking** | No effect | **Breaking** | **Breaking** | **Breaking** |
| `YOLO_CONFIDENCE_THRESHOLD` | No effect | **Behavioural** | No effect | No effect | No effect | No effect | No effect | No effect |
| `assign_worker()` worker status update | No effect | No effect | No effect | **Breaking** | No effect | No effect | **Breaking** | No effect |

> **`fuse_predictions()` output keys changed $\rightarrow$ `complaint_service` Breaking:**  
> `create_complaint()` passes `fuse_predictions()` outputs directly to database persistence and duplicate scoring functions. Renaming keys (e.g. `issue_type` $\rightarrow$ `type`) causes downstream `KeyError` exceptions or missing database values.

---

## SECTION 12 — Security Model

- **Password Hashing**: Salted key-stretching (`scrypt`/`pbkdf2:sha256`). Rejects weak passwords during registration.
- **JWT Auth & HttpOnly Cookies**: Signed HS256 tokens stored in secure HttpOnly cookies, protecting tokens against client-side XSS exfiltration.
- **Rate Limiting**: `Flask-Limiter` caps login attempts (10/min) and complaint submissions (10/hr) to block automated brute-force attacks.
- **IDOR Protection**: Strict ownership checks (`issue["citizen_id"] == current_user["_id"]`) prevent unauthorized users from viewing or modifying other citizens' issues.
- **Role-Based Access Control (RBAC)**: `@require_role()` decorator enforces server-side permission checks regardless of UI client state.
- **NoSQL Injection Prevention**: PyMongo parameterizes all query dictionaries, preventing raw BSON query manipulation.

---

## SECTION 13 — Running the Project

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure environment (.env)
cp .env.example .env
# Set SECRET_KEY, JWT_SECRET, and ADMIN_INVITE_CODE

# 3. Create MongoDB indexes
python scripts/create_indexes.py

# 4. Seed sample test data
python seed_plus.py

# 5. Start dev server
python run.py
# Server: http://127.0.0.1:5000 | Health: http://127.0.0.1:5000/api/health

# 6. Run unit and E2E verification test suites
python -m unittest discover -s tests
python test_e2e_verification.py
```

---

## SECTION 14 — Known Gaps and Honest Limitations

- **Gemini API Quota Limits**: When Gemini API free-tier quotas (HTTP 429) are exceeded, text analysis falls back to local rule-based heuristics (`confidence_type: "heuristic"`).
- **OSRM Router Connectivity**: If the public OSRM router is offline or times out (5s), routing falls back cleanly to `available: false` rather than rendering misleading straight-line polylines.
- **Single-Node In-Memory Limiter**: `Flask-Limiter` uses in-memory storage (`memory://`); multi-instance production clusters should attach a Redis backend storage URI.

---

*SmartCivic System Guide & Technical README — Master Documentation*
