# Pre-Release Hardening Fix Report (`fix/pre-release`)

This report documents the completion of all six pre-release requirements mandated prior to release tagging, executed strictly on branch `fix/pre-release`.

---

## 1. Default-Deny Authorization Architecture

### Implementation Details
- **Decorator Marker Attribute**: Added `_is_auth_protected = True` attribute marker to all security decorators:
  - `require_auth` & `require_role` in `routes/auth.py`
  - `verified_required` & `officer_required` in `utils/auth_helpers.py`
  - `require_citizen_page` in `routes/citizen.py`
  - `require_officer_page` in `routes/officer.py`
  - `require_worker_page` in `routes/worker.py`
- **Missing Protection Hardening**: Secured `/api/analytics/ward-health/<ward>` in `routes/api/analytics.py` with `@require_auth` and `@require_role('officer', 'admin')`.
- **Automated Verification Test**: Implemented `tests/test_default_deny.py`, which introspects `app.url_map` at test time. Any endpoint that lacks an auth decorator marker and is not present in `PUBLIC_ENDPOINTS` triggers an immediate test failure.

### Canonical `PUBLIC_ENDPOINTS` Allowlist (24 Endpoints)
```text
  [PUBLIC] analytics_api.get_public_stats
  [PUBLIC] api_auth.login
  [PUBLIC] api_auth.logout
  [PUBLIC] api_auth.refresh
  [PUBLIC] api_auth.register
  [PUBLIC] api_auth.verify_ward
  [PUBLIC] api_mobile_auth.mobile_login
  [PUBLIC] auth.login
  [PUBLIC] auth.logout
  [PUBLIC] auth.refresh
  [PUBLIC] auth.register
  [PUBLIC] auth.verify_ward
  [PUBLIC] citizen.verify_ward_page
  [PUBLIC] health_check
  [PUBLIC] index
  [PUBLIC] live_map_page
  [PUBLIC] login_page
  [PUBLIC] map_api.get_public_map
  [PUBLIC] private_file
  [PUBLIC] register_page
  [PUBLIC] static
  [PUBLIC] transparency_page
  [PUBLIC] worker.pwa_manifest
  [PUBLIC] worker.service_worker
```

### Verification Result
Command: `pytest tests/test_default_deny.py -v -s`
```text
tests/test_default_deny.py::test_default_deny_all_endpoints PASSED [100%]
1 passed in 1.49s
```

---

## 2. Verification Document Retention Scheduled Purge

### Implementation Details
- **Retention Service**: Created `services/retention_service.py` featuring `purge_expired_verification_documents(retention_days=None, db=None)`.
- **Retention Window**: Configurable via `VERIFICATION_DOC_RETENTION_DAYS` environment variable (default: `30` days).
- **Scheduler Integration**: Registered cron job `verification_doc_retention_job` in `app.py` scheduled daily at `03:00 UTC` protected by MongoDB distributed lock `scheduler_lock("verification_doc_retention_purge")`.
- **Audit Logging**: For every deleted document, the physical encrypted file on disk is removed, the user document's `verification_doc` field is `$unset`, and a structured record is inserted into `audit_logs`:
  ```json
  {
    "action": "verification_doc_purged",
    "user_id": "<ObjectId>",
    "verification_status": "approved",
    "retention_days": 30,
    "timestamp": "<datetime>"
  }
  ```

### Verification Result (Faked Timestamps)
Command: `pytest tests/test_verification_doc_retention.py -v`
```text
tests/test_verification_doc_retention.py::test_verification_doc_retention_purge PASSED [100%]
1 passed in 1.70s
```
*Validated with faked review timestamps: 40-day-old and 35-day-old documents were purged from disk and unlinked, while 5-day-old documents were retained.*

---

## 3. Renamed `AUTO_ROUTE` to `HIGH_CONFIDENCE` & Documentation Cleanup

### Code & UI Changes
- **Constants & Helpers**:
  - `services/ai_classifier.py`: Defined `ROUTE_HIGH_CONFIDENCE = "HIGH_CONFIDENCE"` and backward-compatible alias `AUTO_ROUTE = ROUTE_HIGH_CONFIDENCE`. `_compute_route()` returns `"HIGH_CONFIDENCE"` for confidence $\ge 0.90$.
  - `services/ai_pipeline.py`: Defined `ROUTE_HIGH_CONFIDENCE = "HIGH_CONFIDENCE"`, `AUTO_ROUTE = ROUTE_HIGH_CONFIDENCE`. `compute_route_decision()` returns `"HIGH_CONFIDENCE"`.
  - `routes/api/issues.py`: Updated clarified issue route decision to `"HIGH_CONFIDENCE"`.
  - `templates/smartcivic_v2.html`: Renamed UI label `'Auto-Route Threshold'` to `'High Confidence Threshold'`.
  - `test_smartcivic.py`: Updated assertions to recognize both `"HIGH_CONFIDENCE"` and legacy `"AUTO_ROUTE"`.
- **Backward Compatibility**:
  - Historic issues in MongoDB with `"ai_route_decision": "AUTO_ROUTE"` continue to resolve seamlessly; equality and list checks accept both tokens.

### README Documentation Cleanup
- Updated `README.md` Section 14 to remove unbacked claims:
  - **No Autonomous Dispatch**: Stated clearly that `HIGH_CONFIDENCE` ($\ge 0.90$) is a triage recommendation; SmartCivic does not auto-dispatch field workers without officer triage.
  - **SMS/Email Deferred**: Documented that external SMS (Twilio/Fast2SMS) and email (SMTP/SendGrid) gateways are deferred. Notifications are strictly in-app and real-time WebSockets (`/civic`).
  - **Crowd Consensus Deferred**: Clarified that 3-citizen crowd consensus verification is deferred. Resolution verification is performed between the reporting citizen and municipal officers.

---

## 4. CORS Hardening & Production Startup Enforcement

### Implementation Details
- **Unified Origins**: `_get_cors_origins()` in `app.py` loads `ALLOWED_ORIGINS` (or fallback `CORS_ALLOWED_ORIGINS`).
- **Shared Configuration**: The exact same origin list is bound to:
  - Flask web application: `CORS(app, origins=cors_origins, supports_credentials=True)`
  - Flask-SocketIO real-time engine: `socketio.init_app(app, cors_allowed_origins=cors_origins)`
- **Production Refusal of Localhost**:
  - In `FLASK_ENV=production`, `_validate_runtime_config(Config)` and `_get_cors_origins()` inspect all allowed origins.
  - If any origin contains `localhost`, `127.0.0.1`, or `0.0.0.0`, startup immediately halts with:
    `RuntimeError("CRITICAL: Production mode refuses localhost/loopback in ALLOWED_ORIGINS: '...'")`
  - If `ALLOWED_ORIGINS` is unset or empty in production mode, startup halts with:
    `RuntimeError("CRITICAL: ALLOWED_ORIGINS environment variable must be explicitly defined in production mode.")`

### Verification Result
Command: `pytest tests/test_cors_prerelease.py -v`
```text
tests/test_cors_prerelease.py::TestCorsHardening::test_allowed_origins_parsed_from_env PASSED [ 12%]
tests/test_cors_prerelease.py::TestCorsHardening::test_cors_origins_fallback_to_cors_allowed_origins_env PASSED [ 25%]
tests/test_cors_prerelease.py::TestCorsHardening::test_development_mode_defaults PASSED [ 37%]
tests/test_cors_prerelease.py::TestCorsHardening::test_flask_and_socketio_share_same_cors_origins PASSED [ 50%]
tests/test_cors_prerelease.py::TestCorsHardening::test_production_mode_allows_clean_domains PASSED [ 62%]
tests/test_cors_prerelease.py::TestCorsHardening::test_production_mode_refuses_127_0_0_1 PASSED [ 75%]
tests/test_cors_prerelease.py::TestCorsHardening::test_production_mode_refuses_localhost PASSED [ 87%]
tests/test_cors_prerelease.py::TestCorsHardening::test_production_mode_refuses_missing_allowed_origins PASSED [100%]
8 passed in 2.00s
```

---

## 5. Technical Report: Encryption, Anonymity & Abuse Controls

### 5.1 Where Encryption Key is Loaded From & Failure Behavior
- **Key Derivation Path (`utils/crypto_utils.py:11-28`)**:
  - The symmetric encryption system inspects `VERIFICATION_ENCRYPTION_KEY` in environment variables. If present, it must be a valid 44-character URL-safe base64 string.
  - If unset, it falls back to `SECRET_KEY`, deriving a deterministic 32-byte key via `hashlib.sha256(secret.encode("utf-8")).digest()` and base64-encoding it for Fernet.
- **Missing Key Behavior (`config.py:75`, `app.py:98-102`)**:
  - In `config.py`, `SECRET_KEY = _require_secret("SECRET_KEY")`.
  - In `app.py`, `_validate_runtime_config` evaluates `SECRET_KEY` on startup. If missing, empty, or containing placeholder `replace_`, the server raises `RuntimeError("CRITICAL: SECRET_KEY is not configured securely...")` and **refuses to start**.
  - In non-production/test environments with missing `VERIFICATION_ENCRYPTION_KEY`, it falls back to a development key string.

### 5.2 How an Anonymous Reporter Tracks Their Report
- **Zero Identity in Issue Document**:
  - When a complaint is filed with `is_anonymous: true`, `services/complaint_service.py:204-206` sets `citizen_id = None` and `is_anonymous = True`. No user ID or PII is recorded on the `issues` document.
- **Keyed Cryptographic Indexing (`routes/api/issues.py:163-173`)**:
  - A server-side HMAC is computed using the server's private secret:
    $$\text{reporter\_hash} = \text{HMAC-SHA256}(\text{SECRET\_KEY}, \text{user\_id})$$
  - A separate linking record is inserted into `db.anonymous_reporters`:
    `{"issue_id": issue["_id"], "reporter_hash": reporter_hash, "created_at": ...}`
  - Because HMAC is a keyed one-way function, an attacker who dumps `db.anonymous_reporters` and `db.issues` cannot correlate the complaint to any citizen without `SECRET_KEY`.
- **Authorized Tracking (`routes/api/issues.py:771-782`, `utils/auth_helpers.py:167-178`)**:
  - When the citizen logs into their dashboard or calls `GET /api/issues` / `GET /api/issues/<id>`, the server recalculates $\text{HMAC-SHA256}(\text{SECRET\_KEY}, \text{g.current\_user}["\_id"])$ and queries `db.anonymous_reporters`.
  - Matching complaints are included in the citizen's personal tracking view and pass authorization checks in `authorize_issue_access()`, while public serializers continue to strip all submitter metadata.

### 5.3 How Abuse of Anonymous Reports is Limited
1. **Verified Residency Pre-Condition**:
   - `POST /api/issues` requires `@require_auth` and `@verified_required`. Only citizens who have submitted ward residency proof and been approved by an officer can file complaints. Unverified bots cannot submit complaints.
2. **Aggressive Rate Limiting**:
   - Issue creation is capped at `@limiter.limit("10 per hour")` per IP/user (`routes/api/issues.py:69`), preventing automated flooding.
3. **Computer Vision & Image Gate**:
   - Every submission must pass the automated image quality gate (`services/ai/image_gate.py`). Uploaded photos are inspected with Pillow; corrupted files, screenshots, blurred images, or non-road/non-civic content are rejected with HTTP 400.
4. **Spatial Deduplication**:
   - Haversine scanning (`services/duplicate_service.py`) checks for duplicate complaints within a 200-meter radius ($\ge 0.85$ composite score). Flooding the same location automatically collapses submissions into duplicates (`status: "duplicate"`).

---

## 6. Stage 1 Attack Upload Execution & Real Responses

The five attack upload scenarios from the Stage 1 specification were executed against the active application test client (`tests/test_stage1_attack_uploads.py`). All five attacks were neutralized with the verified live responses below.

### Attack 1: Disguised Executable / PHP Shell (`shell.php.jpg`)
- **Payload**: `<?php phpinfo(); system($_GET['cmd']); ?>` with MIME type `image/jpeg`
- **Endpoint**: `POST /api/issues` (multipart/form-data)
- **Live HTTP Status**: `400 Bad Request`
- **Real Response Body**:
  ```json
  {
    "error": {
      "code": "SECURITY_ERROR",
      "message": "Corrupt or non-image file"
    },
    "success": false
  }
  ```
- **Defense Mechanism**: Content verification via Pillow (`Image.open(file).verify()`) detects non-image payload and aborts before disk persistence.

### Attack 2: Path Traversal Attack in Filename (`../../../../etc/cron.d/malicious.jpg`)
- **Payload**: Valid JPEG image bytes uploaded with traversal filename
- **Endpoint**: `POST /api/issues` (multipart/form-data)
- **Live HTTP Status**: `201 Created`
- **Saved Filename in MongoDB**: `d9b0c0de1bd1466495289626eb4bed23.jpeg`
- **Defense Mechanism**: Filenames are discarded and replaced with randomized hex UUIDs (`uuid.uuid4().hex`). All path separators (`/`, `\`, `..`) are neutralized; file is stored safely in private storage.

### Attack 3: Disguised SVG / Stored XSS Vector (`vector.svg.jpg`)
- **Payload**: `<svg xmlns='http://www.w3.org/2000/svg' onload='alert(document.cookie)'></svg>` with MIME `image/jpeg`
- **Endpoint**: `POST /api/issues` (multipart/form-data)
- **Live HTTP Status**: `400 Bad Request`
- **Real Response Body**:
  ```json
  {
    "error": {
      "code": "SECURITY_ERROR",
      "message": "Corrupt or non-image file"
    },
    "success": false
  }
  ```
- **Defense Mechanism**: Strict image decoder verification rejects XML/SVG payloads masquerading as JPEG.

### Attack 4: Oversized Payload Exceeding `MAX_CONTENT_LENGTH` (> 8MB)
- **Payload**: 9.0 MB dummy byte stream
- **Endpoint**: `POST /api/issues` (multipart/form-data)
- **Live HTTP Status**: `413 Request Entity Too Large`
- **Real Response Body**:
  ```json
  {
    "error": {
      "code": "REQUEST_ENTITY_TOO_LARGE",
      "message": "The data value transmitted exceeds the capacity limit."
    },
    "success": false
  }
  ```
- **Defense Mechanism**: Enforced by WSGI application buffer ceiling `app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024`.

### Attack 5: Direct & Unauthenticated Access to Upload Storage
- **Scenario 5a (Legacy Static Path)**: `GET /static/uploads/verification_docs/confidential_id.jpg`
  - **Live HTTP Status**: `404 Not Found`
  - **Defense Mechanism**: `uploads/` directory moved outside web root (`static/`); static routing returns 404.
- **Scenario 5b (Unauthenticated File Serving Proxy)**: `GET /files/verification_docs/confidential_id.jpg`
  - **Live HTTP Status**: `401 Unauthorized`
  - **Defense Mechanism**: Endpoint requires valid authentication token. Access is strictly governed by ownership and ward role checks.

---

## 7. Pre-Release Test Suite Summary

| Test Module | Coverage Area | Status | Execution Time |
|:---|:---|:---:|:---:|
| `tests/test_default_deny.py` | All URL endpoints vs allowlist | ✅ PASS | 1.49s |
| `tests/test_verification_doc_retention.py` | Retention purge & audit logs | ✅ PASS | 1.70s |
| `tests/test_cors_prerelease.py` | CORS origins & prod localhost refusal | ✅ PASS | 2.00s |
| `tests/test_stage1_attack_uploads.py` | 5 attack upload payloads | ✅ PASS | 2.99s |
| `tests/test_phase3_uploads_privacy.py` | Upload privacy & serializers | ✅ PASS | 3.71s |
| `test_smartcivic.py` | Full core application test suite | ✅ PASS (156/156) | 0.34s |

**Total Regressions: 0**  
Branch `fix/pre-release` is complete, verified, and ready for release tagging.

