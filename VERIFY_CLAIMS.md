# SmartCivic Independent Claims Verification (`VERIFY_CLAIMS.md`)

**Audit Date:** 2026-11-05  
**Auditor Role:** Strict, Adversarial Senior Code Auditor (Read-Only Audit)  
**Verification Method:** Exact code line citation + runtime execution logs and test outputs.

---

## 1. Summary Status Table

| Section | Claim / Requirement | Status | File:Line Evidence | Command / Test Verification |
| :--- | :--- | :---: | :--- | :--- |
| **A.1** | Default-deny `before_request` + Route Matrix | **Partial** | `app.py:326-340`, `tests/test_authz_matrix.py:190-340` | `tests/test_authz_matrix.py` PASSED (1 passed in 2.95s). Route matrix tests all 9 personas. BUT `before_request` in `app.py` only loads context (`g.current_user`); it lacks a centralized `before_request` default-deny 403/404 abort on unlisted routes. |
| **A.2** | Token model: HttpOnly, rotating refresh with reuse detection, logout/role revocation, no localStorage | **Implemented** | `routes/auth.py:72-105, 453-485, 520-536, 761` | Grep for `localStorage` in `static/js/` reveals zero auth tokens stored (only language `smartcivic_lang` and user profile cache `sc_user`). JTI rotation and family revocation active in `routes/auth.py:482`. |
| **A.3** | CSRF exemptions: which blueprints and why | **Implemented** | `app.py:230` | Only `api_mobile_auth_bp` (`/api/auth/mobile/*`) is exempt from CSRF because mobile clients communicate via stateless Bearer tokens in headers. All browser cookie blueprints enforce CSRF. |
| **A.4** | CSP: live header and unsafe-inline / unsafe-eval audit | **Partial** | `app.py:358-365` | Live header contains: `script-src 'self' 'unsafe-inline' 'unsafe-eval' ...` and `style-src 'self' 'unsafe-inline' ...`. Still relies on `'unsafe-inline'` and `'unsafe-eval'` for CDN bundles (Chart.js / Leaflet / inline dashboard scripts). |
| **A.5** | Socket.IO and Flask CORS: allowed origins | **Implemented** | `app.py:60-71` | Production default: `["http://localhost:5000", "http://127.0.0.1:5000", "https://smartcivic.local"]` or parsed from `CORS_ALLOWED_ORIGINS`. Wildcard `*` rejected unless configured in dev. |
| **A.6** | Uploads: validation, size/pixel caps, random filenames, EXIF stripped, non-static, auth proxy | **Implemented** | `routes/api/issues.py:86, 1143, 1151`, `utils/image_gate.py:24-80`, `app.py:235-290` | `tests/test_phase3_uploads_privacy.py` (8/8 passed) & `tests/test_private_uploads.py` (6/6 passed). Direct `/static/uploads` returns 404; `/files/<kind>/<filename>` enforces authorization. |
| **A.7** | Verification documents: access control, encryption at rest, retention | **Partial** | `app.py:268-285`, `utils/crypto_utils.py`, `scripts/harden_mongo.py:41` | Access control verified (cross-ward returns 403). AES-GCM encryption at rest active in `app.py:272`. BUT automated file retention pruning script for old verification docs is missing (only MongoDB audit_logs TTL index exists). |
| **A.8** | Serializer whitelists: no `citizen_id`, `reporter_id`, `phone`, or `text_embedding` exposed | **Implemented** | `utils/serializers.py:30-140` | `test_serializers_field_whitelisting` passed. Anonymous reports omit `citizen_id`; public feeds fuzz coordinates to 3 decimals (~110m). |
| **A.9** | Rate limits: storage backend, limits on login, register, upload, support, AI | **Implemented** | `app.py:76-89`, `routes/auth.py:183, 298`, `routes/api/issues.py:69, 1268, 1719` | Limits enforced: Register (`3/min`), Login (`10/min`), Create Issue (`10/hr`), Support (`20/min`), Map (`20/min`). Backend uses `RATELIMIT_STORAGE_URI` or `MONGO_URI` with fallback to `memory://`. |
| **A.10**| Log redaction | **Implemented** | `services/logger_service.py:49-65` | `_redact_sensitive_data` scrubs `password`, `token`, `access_token`, `refresh_token`, `jwt_secret`, `phone`, and `phone_number` with `[REDACTED]`. |
| **B.1** | FLOW-11: Whistleblower anonymous reporting | **Implemented** | `routes/api/issues.py:150-173`, `utils/serializers.py:88-90` | Verified via live test: DB document stores `citizen_id: None, is_anonymous: True`. API GET returns 403 to non-owner; serializers strip identity. |
| **B.2** | FLOW-12: SMS / Email implementation & cost | **Missing** | `services/notification_service.py:1-135` | Zero SMS (Twilio/Fast2SMS) or Email (Flask-Mail/SendGrid) code exists. Completely absent. Cost is $0 because it does not exist. |
| **B.3** | FLOW-14: `db.complaints` vs `db.issues` split | **Implemented** | `routes/`, `services/`, `models/` | Active application code contains 0 references to `db.complaints`. Active DB has 455 issues in `db.issues` and 16 stale documents in legacy `db.complaints`. |
| **B.4** | DEP-01: Git history credentials purge | **Unverified (Manual)**| `git log` | Git history cleaning (`git-filter-repo` / BFG) requires manual human operator action per Phase 0 rules. Cannot be done or verified solely by code in repo workspace. |
| **B.5** | DEP-09: Cloud object storage (S3/R2) | **Missing** | `app.py:263`, `config.py` | Uploads are stored on local filesystem disk (`uploads/`). No S3 or Cloudflare R2 driver is implemented in the repository. |
| **B.6** | DEP-12: Automated database restore script | **Implemented** | `scripts/restore_db.py:1-120` | `scripts/restore_db.py` exists, restores collections, and calls `create_indexes()`. Verified via `test_backup_restore_roundtrip` (passed in 19.95s). |
| **B.7** | DEP-13: Removal of CSP `unsafe-inline` | **Missing** | `app.py:358-365` | `unsafe-inline` and `unsafe-eval` are still hardcoded in `app.py`. |
| **B.8** | AI-03: Kannada translation fallback | **Partial** | `services/ai_service.py:615-660` | Offline dictionary translation appends English civic keywords `(pothole road damage ...)`. When Gemini is rate-limited (429), dictionary appends keywords, but downstream `_rule_based_fallback` still classifies raw non-English text as `other` if keywords are not parsed. |
| **B.9** | AI-09: `AUTO_ROUTE` dispatch to workers | **Missing** | `routes/api/issues.py:1691` | `AUTO_ROUTE` is strictly a string tag set in MongoDB (`target["ai_route_decision"] = "AUTO_ROUTE"`). It does NOT trigger worker assignment or external dispatch. |
| **C.1** | Emergency detection recall & false positives | **Ready for Evaluation** | `services/ai_classifier.py:18-50` | Pattern regex includes medical, fire, chemical, structural collapse, and Kannada/Hinglish triggers. Awaiting test execution on user-provided 80 phrases. |

---

## 2. Detailed Technical Evidence

### 2.1 Default-Deny Authorization & Route Matrix (Item A.1)
- **Matrix Test Execution**:
  ```
  pytest tests/test_authz_matrix.py -v
  ============================= test session starts =============================
  tests/test_authz_matrix.py::TestAuthzMatrixPhase1::test_run_authz_matrix PASSED [100%]
  1 passed in 2.95s
  ```
- **Finding**: While every protected route explicitly uses `@require_auth`, `@require_role`, or `@verified_required` and passes the 9-persona matrix test, there is **no centralized `before_request` default-deny firewall** in `app.py`. An unregistered route missing decorators defaults to whatever Flask allows unless decorated.

### 2.2 Live Content-Security-Policy (CSP) Header (Item A.4)
Captured directly from `GET /login`:
```http
Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://unpkg.com https://fonts.googleapis.com https://fonts.gstatic.com https://raw.githubusercontent.com https://*.openstreetmap.org https://*.tile.openstreetmap.org https://tile.openstreetmap.org http://router.project-osrm.org https://router.project-osrm.org https://nominatim.openstreetmap.org; style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://unpkg.com https://fonts.googleapis.com https://fonts.gstatic.com https://raw.githubusercontent.com https://*.openstreetmap.org https://*.tile.openstreetmap.org https://tile.openstreetmap.org http://router.project-osrm.org https://router.project-osrm.org https://nominatim.openstreetmap.org; img-src 'self' data: blob: https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://unpkg.com https://fonts.googleapis.com https://fonts.gstatic.com https://raw.githubusercontent.com https://*.openstreetmap.org https://*.tile.openstreetmap.org https://tile.openstreetmap.org http://router.project-osrm.org https://router.project-osrm.org https://nominatim.openstreetmap.org; font-src 'self' data: https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://unpkg.com https://fonts.googleapis.com https://fonts.gstatic.com https://raw.githubusercontent.com https://*.openstreetmap.org https://*.tile.openstreetmap.org https://tile.openstreetmap.org http://router.project-osrm.org https://router.project-osrm.org https://nominatim.openstreetmap.org; connect-src 'self' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://unpkg.com https://fonts.googleapis.com https://fonts.gstatic.com https://raw.githubusercontent.com https://*.openstreetmap.org https://*.tile.openstreetmap.org https://tile.openstreetmap.org http://router.project-osrm.org https://router.project-osrm.org https://nominatim.openstreetmap.org ws: wss:;
```
- **Unsafe Directives Present**:
  - `script-src`: contains `'unsafe-inline'` and `'unsafe-eval'`.
  - `style-src`: contains `'unsafe-inline'`.

### 2.3 Uploads Security Verification (Item A.6)
Execution of Stage 1 Upload Tests (`tests/test_private_uploads.py`):
```
pytest tests/test_private_uploads.py -v
============================= test session starts =============================
tests/test_private_uploads.py::test_anonymous_request_gets_401 PASSED    [ 16%]
tests/test_private_uploads.py::test_legacy_static_uploads_returns_404 PASSED [ 33%]
tests/test_private_uploads.py::test_another_citizen_requesting_id_doc_gets_403 PASSED [ 50%]
tests/test_private_uploads.py::test_reporter_and_officer_get_200 PASSED  [ 66%]
tests/test_private_uploads.py::test_invalid_kind_returns_404 PASSED      [ 83%]
tests/test_private_uploads.py::test_acceptance_no_login_uploads_do_not_load PASSED [100%]
6 passed in 1.98s
```

### 2.4 Live Anonymous Report Verification (Item B.1 — FLOW-11)
Executed live submission test against `/api/issues`:
- **API POST Response**:
  ```json
  {
    "success": true,
    "data": {
      "id": "SC-2026-943DB7",
      "title": "Anon Pothole Test",
      "is_anonymous": true,
      "is_owner": false,
      "location": { "coordinates": [77.59, 12.97], "fuzzed": true }
    }
  }
  ```
- **MongoDB Stored Document**:
  ```python
  {'citizen_id': None, 'is_anonymous': True}
  ```
- **API GET by Anonymous Requester**:
  ```json
  {"error": {"code": "FORBIDDEN", "message": "Access restricted to issue owner."}, "success": false}
  ```

---

## 3. Deficiencies & Work Remaining (Honest Audit)

The following items are **NOT FULLY DONE** and must not be marked as complete:

1. **DEP-01 (Credential Purge in Git Packfiles)**:
   - Must be executed by the developer using `git-filter-repo` / BFG and forced pushed. Code commits inside the repo cannot scrub past packfiles.
2. **DEP-09 (Cloud Object Storage — S3 / Cloudflare R2)**:
   - Files are stored on local container disk in `uploads/`. Running on ephemeral containers (e.g. Render / Heroku / Fly.io) will cause upload file loss on dyno restart.
3. **DEP-13 (CSP Hardening)**:
   - `unsafe-inline` and `unsafe-eval` remain active in `app.py`. Nonce-based CSP or bundling inline scripts into external files is required.
4. **FLOW-12 (SMS / Email Service)**:
   - Completely absent. No SDK (Twilio, SendGrid, SMTP) is integrated.
5. **AI-09 (Automatic Worker Dispatch on High Confidence)**:
   - Issues with $\ge 0.90$ confidence are tagged `"AUTO_ROUTE"`, but no automatic worker assignment routine is invoked.
6. **Verification Document Retention Purge (Item A.7)**:
   - Documents are encrypted at rest with AES-GCM, but there is no background cron job or retention policy to delete verified ID cards after 30/90 days.
7. **Centralized Default-Deny Firewall (Item A.1)**:
   - Protection relies on per-route decorators (`@require_auth`, `@require_role`); missing a top-level `before_request` URL map whitelist.

