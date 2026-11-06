# SmartCivic: Comprehensive Project Specifications, Tech Stack & Engineering Innovations

This document details every technological component, software library, database collection, architectural module, security defense, and newly engineered feature in the SmartCivic platform.

---

## 1. Technological Stack Matrix

| Layer | Technology | Version | Purpose in SmartCivic |
| :--- | :--- | :--- | :--- |
| **Backend Framework** | Python / Flask | 3.10.11 / 3.0.x | Core WSGI application server, REST APIs, session management |
| **Database Engine** | MongoDB Community | 7.0.x | NoSQL document storage, 2dsphere spatial indexes, TTL indexes |
| **ODM / DB Driver** | PyMongo | 4.6.x | Native Python MongoDB driver with connection pooling |
| **Real-Time WebSockets** | Flask-SocketIO / Eventlet | 5.3.x / 0.35.x | Bi-directional event bus for live map, announcements, and alerts |
| **Edge Vision Inference** | ONNX Runtime | 1.20.1 | CPU-optimized execution of quantized YOLOv8n road detector |
| **Machine Learning / NLP** | Scikit-Learn | 1.4.x | TF-IDF feature extraction, SGDClassifier for offline text triage |
| **Spatial Graph Engine** | NetworkX | 3.2.x | Urban road network modeling, Dijkstra routing, infrastructure graph |
| **Image Processing** | Pillow (PIL) | 10.2.x | EXIF metadata extraction, dHash difference hashing, thumbnailing |
| **Frontend Architecture** | Vanilla ES6+ / HTML5 | ECMAScript 2022 | Lightweight zero-framework PWA, zero unsafe `innerHTML` |
| **Interactive Mapping** | Leaflet.js (Self-Hosted) | 1.9.4 | Geospatial map rendering, ward boundary GeoJSON, pin clustering |
| **Data Visualization** | Chart.js (Self-Hosted) | 4.4.x | Real-time analytics, ward health trends, municipal forecasting |
| **Security Suite** | Flask-Limiter / WTForms | 3.5.x / 3.1.x | Rate limiting, double-submit CSRF protection, cryptographic auth |
| **Testing & E2E Suite** | Pytest / Playwright | 9.1.x / 1.42.x | Unified test execution across 233 unit, integration, and E2E specs |

---

## 2. Database Schema & Collections

SmartCivic utilizes 12 optimized collections within the `smartcivic` MongoDB database:

1. **`users`:** Stores citizen, worker, officer, and administrator accounts.
   - Fields: `_id`, `email`, `password` (bcrypt/werkzeug hash), `role` (`citizen`, `worker`, `officer`, `admin`), `ward`, `verified` (bool), `verification_status` (`pending`, `verified`, `rejected`), `status` (`active`, `locked`), `civic_score` (int, default 100), `active_assignments` (int, 0–5 for workers), `is_available` (bool), `last_location` (GeoJSON Point), `location_updated_at` (datetime), `failed_attempts` (int), `lockout_until` (datetime).
   - Indexes: `email` (unique), `role`, `ward`, `last_location` (2dsphere).

2. **`issues`:** Central grievance and municipal defect records.
   - Fields: `_id`, `title`, `description`, `category` (roads, water, garbage, electricity, etc.), `status` (`submitted`, `assigned`, `in_progress`, `work_completed`, `resolved`, `closed`, `rejected`), `priority` (P0, P1, P2, P3), `cips_score` (float 0.0–1.0), `location` (GeoJSON Point `[lng, lat]`), `address`, `ward`, `citizen_id` (ObjectId), `worker_id` (ObjectId, nullable), `assigned_at`, `resolved_at`, `image_url`, `after_image_url`, `dhash` (string), `cluster_id` (string), `sla_deadline` (datetime).
   - Indexes: `location` (2dsphere), `status`, `ward`, `worker_id`, `citizen_id`, `cips_score`, `created_at`.

3. **`announcements`:** Administrative municipal bulletins.
   - Fields: `_id`, `title`, `body`, `severity` (`info`, `warning`, `critical`), `audience` (`citizen`, `worker`, `both`), `pinned` (bool), `status` (`active`, `retracted`), `created_by` (ObjectId), `created_at`, `expires_at`, `idempotency_key`.
   - Indexes: `status`, `expires_at`, `created_at`, `idempotency_key` (sparse).

4. **`announcement_reads`:** Per-user read receipt ledger.
   - Fields: `_id`, `announcement_id` (ObjectId), `user_id` (ObjectId), `read_at` (datetime).
   - Indexes: Compound unique index `(announcement_id, user_id)`.

5. **`audit_logs`:** Immutable audit trail for administrative and dispatch actions.
   - Fields: `_id`, `action` (`JOB_ASSIGNED`, `JOB_REASSIGNED`, `STATUS_CHANGE`, `ADMIN_ANNOUNCEMENT_BROADCAST`, `ADMIN_ANNOUNCEMENT_RETRACTED`), `entity_type`, `entity_id` (ObjectId), `actor_id` (ObjectId), `actor_role`, `details` (dict), `timestamp` (datetime).
   - Indexes: `action`, `entity_id`, `actor_id`, `timestamp`.

6. **`ward_registry`:** Canonical municipal boundaries and administrative jurisdiction metadata.
   - Fields: `ward_id`, `ward_name`, `zone`, `boundary` (GeoJSON Polygon), `assigned_officer_id`.
   - Indexes: `boundary` (2dsphere), `ward_id` (unique).

7. **`repair_evidence`:** Verified proof-of-work documentation submitted by field workers.
   - Fields: `_id`, `issue_id` (ObjectId), `worker_id` (ObjectId), `after_image_url`, `verdict` (`repaired`, `incomplete`, `mismatch`), `confidence` (float), `ssim_score` (float), `created_at`.
   - Indexes: `issue_id`, `worker_id`.

8. **`duplicate_links`:** Spatiotemporal clustering records mapping duplicate complaints to parent issues.
   - Fields: `_id`, `parent_issue_id` (ObjectId), `duplicate_issue_id` (ObjectId), `distance_meters` (float), `dhash_distance` (int), `created_at`.
   - Indexes: `parent_issue_id`, `duplicate_issue_id`.

9. **`forecasts`:** Rolling-origin predictive demand forecasts.
   - Fields: `_id`, `ward_id`, `category`, `horizon_months`, `expected_reporting_volume` (float), `confidence_interval` (dict), `metric_description`, `computed_at`.
   - Indexes: `ward_id`, `category`.

10. **`notifications`:** Real-time push notifications dispatched to user dashboards.
    - Fields: `_id`, `user_id` (ObjectId), `title`, `message`, `type`, `read` (bool), `created_at`.
    - Indexes: `user_id`, `read`, `created_at`.

11. **`image_hashes`:** Perceptual difference hashes for duplicate image indexing.
    - Fields: `_id`, `issue_id` (ObjectId), `dhash` (string), `created_at`.
    - Indexes: `dhash`.

12. **`worker_locations`:** Transient historical GPS tracks for active field workers with 24-hr TTL eviction.
    - Fields: `_id`, `worker_id` (ObjectId), `location` (GeoJSON Point), `timestamp` (datetime).
    - Indexes: `location` (2dsphere), `timestamp` (TTL index: 86,400 seconds).

---

## 3. Engineering Innovations & Added Features

### 3.1 Real-Time Municipal Announcement Broadcast Subsystem
- **Purpose:** Enables municipal administrators to broadcast authoritative city bulletins (road closures, storm advisories, emergency repair schedules) with real-time push.
- **REST Endpoints:**
  - `POST /api/admin/announcements`: Admin compose endpoint with plain-text sanitization, severity validation (`info`, `warning`, `critical`), audience targeting (`citizen`, `worker`, `both`), idempotency key deduplication, and audit logging.
  - `GET /api/announcements/active`: Retrieves non-expired active announcements filtered by the authenticated user's role.
  - `POST /api/announcements/<id>/read`: Records individual user read status, updating unread badges without duplicate entries.
  - `POST /api/admin/announcements/<id>/retract`: Admin retraction endpoint marking status as retracted and pushing real-time removal events over Socket.IO.
  - `GET /api/admin/announcements`: Admin history endpoint returning all broadcasts with aggregate read counts.
- **Real-Time Socket.IO Integration:** Broadcasts immediately emit `announcement_broadcast` to `/civic` namespace in `role_citizen`, `role_resident`, and `role_worker` rooms. Retractions emit `announcement_retracted`.
- **UI Presentation:** Dismissible notification banner (`#activeAnnouncementBanner`) rendered cleanly in `templates/base.html` above the main content area for authenticated users.

### 3.2 Concurrency-Safe Atomic Worker Assignment
- **Problem Solved:** Prior static databases experienced race conditions where concurrent officer assignments overwhelmed field workers, exceeding safe labor capacities.
- **Implementation (`services/assignment_service.py`):**
  - **Atomic Check-and-Set:** Updates issue status conditionally using `db.issues.update_one({"_id": issue_id, "status": {"$in": ["submitted", "assigned"]}}, ...)`.
  - **Prior Worker Release:** Automatically decrements the active assignment count of the prior worker if an issue is reassigned.
  - **Capacity Ceiling:** Rejects assignments with HTTP 400 if a worker has $\ge 5$ active assignments or is marked unavailable.
  - **Race Safety:** Validated with concurrent threading tests in `tests/test_worker_assignment_atomic.py`.

### 3.3 Active-Dispatch-Gated Live Geolocation Tracking
- **Privacy Enforcement:** Field workers' real-time GPS locations are shared **only** while actively dispatched to a task (`status in ['assigned', 'in_progress', 'work_started', 'en_route']`).
- **Telemetry Limits:** Location updates are rate-limited to 6 per minute (`routes/api/workers.py`).
- **Data Retention:** Stored locations expire automatically after 24 hours via MongoDB TTL indexes.
- **Non-Public Access:** Worker telemetry is queryable exclusively by authorized ward officers and administrators; never exposed on public maps.
- **Citizen GPS Fallback:** Added `#btnLocateMe` button with graceful fallback to manual map pin dropping if geolocation is blocked or unavailable.

### 3.4 Multi-Lingual Kannada NLP Triage
- **Vernacular Lexicon:** Curated dictionary of 80+ Kannada keywords and transliterated terms mapped to BBMP municipal departments (e.g., ರಸ್ತೆ ಗುಂಡಿ / *gundi* $\rightarrow$ Roads; ಕಸ / *kasa* $\rightarrow$ Solid Waste; ಬೀದಿ ದೀಪ / *beedi deepa* $\rightarrow$ Electrical).
- **Offline ML Fallback:** SGDClassifier trained on TF-IDF unigram and bigram features runs locally without network access, achieving 42.42% top-1 accuracy on real-world multi-lingual complaints.

### 3.5 Cryptographic & Computer Vision Proof-of-Work
- **Resolution Proof:** Resolving an issue requires uploading photographic evidence of the completed repair.
- **CTVE Modal Verification:** Runs automated computer vision checks comparing before and after images to detect matching backgrounds and verify defect remediation.

---

## 4. Security Hardening Architecture

1. **Content Security Policy (CSP):**
   - No wildcards (`*`) and no `'unsafe-inline'` / `'unsafe-eval'`.
   - All third-party fonts (Inter, Playfair Display), icons (FontAwesome), and libraries (Leaflet, Chart.js, Socket.IO) are self-hosted under `/static/vendor/`.
2. **Session Security:**
   - JWT tokens stored exclusively in `HttpOnly`, `SameSite=Lax` cookies.
   - Double-submit CSRF tokens required on all mutating HTTP methods (`POST`, `PUT`, `DELETE`).
3. **Upload Quarantine:**
   - Multi-stage memory-bound validator checks MIME magic numbers, file size ($\le 8\text{MB}$), strips EXIF metadata, and rejects disguised executables (`.php.jpg`, `.exe`).
4. **Default-Deny URL Authorization:**
   - Global `before_request` interceptor blocks any endpoint not explicitly registered in the role access matrix.

---

## 5. Operations & Execution Guide

### 5.1 Environment Configuration (`.env`)
```bash
APP_ENV=development
FLASK_ENV=development
SECRET_KEY=<cryptographic-random-secret>
JWT_SECRET_KEY=<cryptographic-random-jwt-key>
MONGO_URI=mongodb://127.0.0.1:27017/smartcivic
RATE_LIMIT_ENABLED=true
WTF_CSRF_ENABLED=true
COOKIE_SECURE=false # Set true in HTTPS production
```

### 5.2 Terminal Commands

#### Seed Development Database:
```bash
python scripts/seed_demo.py
```

#### Run Local Development Server:
```bash
python app.py
# Server binds to http://127.0.0.1:5000
```

#### Execute Complete Test Suite:
```bash
pytest -q
# Runs all 233 tests (Unit, Integration, and Playwright E2E)
```

#### Run Playwright End-to-End Tests:
```bash
pytest tests/e2e -v
```

#### Run Secret & Security Scanners:
```bash
detect-secrets scan
pip-audit
```
