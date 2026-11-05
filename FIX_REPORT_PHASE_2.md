# Phase 2 Fix Report: Sessions, Tokens, CSRF, XSS, and Browser Defenses

**Branch:** `fix/phase-2`  
**Status:** ✅ Completed & Fully Verified  
**Date:** 2026-11-05  
**Automated Tests:** 146 passed (including 10 new dedicated Phase 2 security test cases)

---

## 1. Executive Summary

Phase 2 remediation focuses on web session security, token lifecycle management, cross-site attack mitigation (CSRF & XSS), secure browser response headers, rate limiting, and third-party API circuit breaking. 

Every requirement outlined in [SMARTCIVIC_FIX_PLAN.md](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/SMARTCIVIC_FIX_PLAN.md#L50-L76) under **Phase 2: Sessions, tokens, browser defenses** has been implemented and verified with automated test suites targeting the `smartcivic_test` environment.

---

## 2. Detailed Task Remediation Breakdown

### Task 2.1: Token Model & Session Revocation
- **15-Minute Access Tokens:** Shortened JWT access token lifetime from 30 minutes to 15 minutes (`timedelta(minutes=15)`).
- **Refresh Token Rotation & Hashed Storage:** Refresh tokens now carry a cryptographically secure `jti` and `family_id`. Their SHA-256 hashes are tracked in `db.refresh_tokens` alongside metadata (`issued_at`, `revoked`, `user_id`).
- **Reuse Detection:** If an already-rotated or revoked refresh token is presented at `/api/auth/refresh`, the entire session family (`family_id`) is instantly revoked, and an HTTP 401 (`TOKEN_REUSE_DETECTED`) is returned.
- **Revocation on State Changes:** Active refresh tokens are revoked on `/api/auth/logout` and when an authority rejects a resident/worker registration.
- **LocalStorage Leak Elimination:** Deleted orphaned [static/js/auth.js](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/static/js/auth.js), removed access/refresh token caching in browser `localStorage`/`sessionStorage` in [static/js/utils.js](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/static/js/utils.js) and [templates/auth/verify_ward.html](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/templates/auth/verify_ward.html). Web authentication relies exclusively on `HttpOnly`, `SameSite=Lax` cookies.

### Task 2.2: CSRF Hardening
- **Smart CSRF Protection:** Implemented `SmartCivicCSRFProtect` in [app.py](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/app.py). Mobile API clients providing `Authorization: Bearer <token>` remain exempt from CSRF checks.
- **Removed Blanket Blueprint Exemption:** Removed blanket `csrf.exempt(...)` calls from cookie-authenticated blueprints (`issues_api_bp`, `analytics_api_bp`, `workers_api_bp`, `notifications_api_bp`, `map_api_bp`, etc.).
- **Automated Frontend CSRF Injection:** Intercepted `window.fetch` in [static/js/utils.js](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/static/js/utils.js) to automatically attach `X-CSRFToken` from `<meta name="csrf-token">` and `credentials: "same-origin"` on all state-changing requests (`POST`, `PUT`, `DELETE`, `PATCH`).
- **Hidden Form Inputs:** Embedded `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">` inside HTML forms across [templates/auth/login.html](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/templates/auth/login.html), [templates/auth/register.html](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/templates/auth/register.html), [templates/auth/verify_ward.html](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/templates/auth/verify_ward.html), [templates/report_issue.html](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/templates/report_issue.html), and [templates/citizen/dashboard.html](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/templates/citizen/dashboard.html).

### Task 2.3: XSS Defense in Depth (FE-01 to FE-04, RT-01)
- **Global HTML Escaping Utility:** Created and globally exported `escapeHtml(str)` in [static/js/utils.js](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/static/js/utils.js).
- **Toast Injection Neutralized (FE-04, RT-01):** Modified [static/js/toast.js](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/static/js/toast.js) to set `msgSpan.textContent = message` instead of injecting raw HTML strings into `.innerHTML`.
- **Citizen Card Sanitization (FE-01):** Sanitized issue title, description, address, severity, status, and ID in [static/js/citizen.js](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/static/js/citizen.js).
- **Dashboard & Leaflet Popup Sanitization (FE-02, FE-03):** Sanitized dynamic cards, Leaflet map popup contents, natural-language search results, and pending account approval queues in [static/js/dashboard.js](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/static/js/dashboard.js).
- **Worker Card Sanitization:** Sanitized job titles, descriptions, and addresses in [static/js/worker.js](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/static/js/worker.js).
- **Template Audit:** Verified zero occurrences of `|safe` or `| safe` over user-controlled input in Jinja2 templates.

### Task 2.4: Headers, CORS, Cookies & Reverse Proxy Hardening
- **Security Response Headers:** Configured strict HTTP headers in [app.py](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/app.py):
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `X-XSS-Protection: 1; mode=block`
  - `Strict-Transport-Security: max-age=31536000; includeSubDomains`
  - `Referrer-Policy: strict-origin-when-cross-origin`
  - `Permissions-Policy: geolocation=(self), camera=(self), microphone=()`
- **Restricted Socket.IO CORS Origins:** Replaced `cors_allowed_origins="*"` with an environment allowlist (`CORS_ALLOWED_ORIGINS`) defaulting to specific origins (`http://localhost:5000`, `http://127.0.0.1:5000`, `https://smartcivic.local`).
- **Secure Cookie Default (DEP-10):** Changed `COOKIE_SECURE` in [config.py](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/config.py) to default to `True` unless `FLASK_ENV == "development"`.
- **Forwarded IP Spoofing Fix (DEP-16):** Replaced `--forwarded-allow-ips='*'` with restricted `--forwarded-allow-ips='${FORWARDED_ALLOW_IPS:-127.0.0.1}'` in [Dockerfile](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/Dockerfile), [Procfile](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/Procfile), and [run.py](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/run.py).

### Task 2.5: Rate Limiting & Gemini Circuit Breaker
- **Rate Limits on Sensitive Endpoints:** Added `@limiter.limit` decorators to:
  - Account verification: `/api/auth/users/<id>/verify` (`30 per minute`)
  - Issue confirmation: `/api/issues/<id>/confirm` (`20 per minute`)
  - Duplicate confirmation: `/api/issues/<id>/duplicate-confirm` (`20 per minute`)
  - Complaint community support: `/api/issues/<id>/support` (`20 per minute`)
- **Gemini Circuit Breaker & Cost Cap:** Added `GeminiCircuitBreaker` in [services/ai_service.py](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/services/ai_service.py) with:
  - 5-failure threshold tripping circuit state to `OPEN`.
  - Immediate trip on HTTP 429 (`ResourceExhausted` / quota limit).
  - 60-second recovery timeout (`HALF_OPEN` probe).
  - Configurable daily call limit (`GEMINI_DAILY_CALL_LIMIT`, default 1000) preventing runaway cloud bills.

---

## 3. Verification & Gate Evidence

### Dedicated Test Suite: `tests/test_phase2_tokens_csrf_xss.py`
Command: `pytest tests/test_phase2_tokens_csrf_xss.py -v`
```
============================= test session starts =============================
platform win32 -- Python 3.10.11, pytest-9.1.1, pluggy-1.6.0
rootdir: C:\Users\Muthaheer\Desktop\main project\code 1
configfile: pytest.ini
collected 10 items

tests/test_phase2_tokens_csrf_xss.py::TestPhase2TokensAndDefenses::test_access_token_has_15_min_expiry PASSED [ 10%]
tests/test_phase2_tokens_csrf_xss.py::TestPhase2TokensAndDefenses::test_csrf_enforcement_and_bearer_exemption PASSED [ 20%]
tests/test_phase2_tokens_csrf_xss.py::TestPhase2TokensAndDefenses::test_gemini_circuit_breaker_and_quota_cap PASSED [ 30%]
tests/test_phase2_tokens_csrf_xss.py::TestPhase2TokensAndDefenses::test_httponly_and_samesite_cookies PASSED [ 40%]
tests/test_phase2_tokens_csrf_xss.py::TestPhase2TokensAndDefenses::test_logout_revokes_tokens PASSED [ 50%]
tests/test_phase2_tokens_csrf_xss.py::TestPhase2TokensAndDefenses::test_refresh_token_reuse_revokes_entire_family PASSED [ 60%]
tests/test_phase2_tokens_csrf_xss.py::TestPhase2TokensAndDefenses::test_refresh_token_rotation_and_storage PASSED [ 70%]
tests/test_phase2_tokens_csrf_xss.py::TestPhase2TokensAndDefenses::test_rejection_revokes_tokens PASSED [ 80%]
tests/test_phase2_tokens_csrf_xss.py::TestPhase2TokensAndDefenses::test_security_headers_present PASSED [ 90%]
tests/test_phase2_tokens_csrf_xss.py::TestPhase2TokensAndDefenses::test_xss_protection_and_html_escaping PASSED [100%]

============================= 10 passed in 3.37s ==============================
```

### Full Regression Suite
Command: `pytest tests/`
```
============================ 146 passed in 25.08s =============================
```

---

## 4. Remediation Matrix

| ID | Finding | File(s) | Fix Summary | Verdict |
| :--- | :--- | :--- | :--- | :--- |
| **P2-01** | 30m Access Token Lifetime | `routes/auth.py` | Reduced access token lifetime to 15m. | ✅ Verified |
| **P2-02** | Refresh Token Invalidation | `routes/auth.py` | Added SHA-256 hashed tracking in `db.refresh_tokens`, rotation, reuse detection. | ✅ Verified |
| **P2-03** | LocalStorage Token Leak | `static/js/auth.js`, `utils.js` | Deleted `auth.js`, removed localStorage token reads/writes. | ✅ Verified |
| **P2-04** | Blanket CSRF Exemption | `app.py` | Removed blueprint exemptions; created `SmartCivicCSRFProtect` exempting Bearer tokens. | ✅ Verified |
| **P2-05** | Stored XSS Dynamic Injection | `static/js/citizen.js`, `dashboard.js`, `toast.js`, `worker.js` | Sanitized with `escapeHtml` and `textContent`. | ✅ Verified |
| **P2-06** | Insecure Cookie Defaults | `config.py` | Defaulted `COOKIE_SECURE = True` outside development. | ✅ Verified |
| **P2-07** | Proxy IP Spoofing | `Dockerfile`, `Procfile`, `run.py` | Replaced wildcard `--forwarded-allow-ips='*'` with CIDR/127.0.0.1. | ✅ Verified |
| **P2-08** | Wildcard Socket.IO CORS | `app.py` | Replaced wildcard with restricted domain allowlist. | ✅ Verified |
| **P2-09** | Missing Rate Limits | `routes/api/issues.py`, `routes/auth.py` | Added `@limiter.limit` to verify, support, and confirm endpoints. | ✅ Verified |
| **P2-10** | Gemini Quota Exhaustion | `services/ai_service.py` | Implemented `GeminiCircuitBreaker` and daily cost cap. | ✅ Verified |

---

## 5. Next Steps

With Phase 2 verified and closed, the next phase per `SMARTCIVIC_FIX_PLAN.md` is:
**Phase 3: Uploads, PII and privacy**
- Upload content validation (Pillow verify, PDF magic bytes, decompression bomb pixel cap).
- UUID filename enforcement and metadata/EXIF stripping.
- Authenticated file serving (never serve uploads from public static).
- Verification document Fernet encryption at rest.
- Field whitelisting serializers (`public_issue`, `citizen_issue`, `officer_issue`) to eliminate raw document leakage.
- PII scrubbing before Gemini API calls.

