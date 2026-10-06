# SMARTCIVIC+ — KNOWN ISSUES & RESOLUTION LOG

**Last Audit:** September 7, 2026  
**System Status:** 0 UNRESOLVED CRITICAL ISSUES

---

## 1. Resolved Issues Log

### ISSUE-001: Missing `citizen_id` KeyError on Status Update
- **Category:** Backend Exception / Data Safety
- **Component:** `services/complaint_service.py`
- **Description:** Updating status of a complaint created without an explicit `citizen_id` (e.g. system generated or mock test records) caused a python `KeyError: 'citizen_id'`, triggering HTTP 500.
- **Fix Applied:** Refactored `update_status` to safely retrieve `citizen_id = issue.get("citizen_id")` before sending status notifications.
- **Verification:** Verified by `test_worker_job_lifecycle` in `qa/test_qa_suite.py`.

### ISSUE-002: Content-Security-Policy (CSP) OpenStreetMap & OSRM Blocking
- **Category:** Browser Security & Map Assets
- **Component:** `app.py` (`add_security_headers`)
- **Description:** Leaflet map tiles from `*.tile.openstreetmap.org` and routing requests to `router.project-osrm.org` were blocked silently by strict CSP headers on web browsers.
- **Fix Applied:** Explicitly added `https://*.tile.openstreetmap.org`, `https://tile.openstreetmap.org`, `http://router.project-osrm.org`, `https://router.project-osrm.org`, and `https://nominatim.openstreetmap.org` to `trusted_cdns` inside `app.py`.
- **Verification:** Verified by `test_security_headers_present` in `qa/test_qa_suite.py`.

### ISSUE-003: Location Detection & Form Binding Mismatch
- **Category:** Frontend UI / Form Integration
- **Component:** `static/js/citizen.js`, `templates/citizen/dashboard.html`, `templates/report_issue.html`
- **Description:** Hidden latitude/longitude form inputs lacked `name="lat"` and `name="lng"` attributes required by standard form serialization, and location button relied on an obsolete function name.
- **Fix Applied:** Standardized location detection function to `locateMe()` and added named hidden inputs `<input type="hidden" id="lat" name="lat">`.
- **Verification:** Verified by `test_citizen_create_issue_and_verify`.

---

## 2. External Dependencies & Operational Notes

1. **Google Gemini API Key (`GEMINI_API_KEY`)**
   - **Status:** OPTIONAL WITH AUTOMATIC FALLBACK
   - **Note:** If `GEMINI_API_KEY` environment variable is omitted or invalid, `services/ai_service.py` automatically falls back to rule-based NLP triage and analytical query parsing without throwing runtime errors or disrupting user complaints.

2. **OSRM Public Routing API (`router.project-osrm.org`)**
   - **Status:** OPERATIONAL WITH FALLBACK
   - **Note:** The route service falls back to Haversine straight-line distance if the public OSRM demonstration server experiences external rate limits or downtime.

3. **Browser Geolocation API (HTTPS / Localhost Requirement)**
   - **Status:** BROWSER SECURITY REQUIREMENT
   - **Note:** Web browsers strictly require HTTPS or `http://127.0.0.1:5000` to expose `navigator.geolocation`. If accessed via plain IP over LAN without HTTPS, standard fallback Bangalore coordinates are maintained.
