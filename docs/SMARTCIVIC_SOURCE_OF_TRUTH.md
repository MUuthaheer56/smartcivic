# SMARTCIVIC+ — SOURCE OF TRUTH ARCHITECTURE SPECIFICATION

**Version:** 2.0.0-PROD  
**Last Updated:** September 7, 2026  
**Status:** FULLY VERIFIED & IMPLEMENTED

---

## 1. Executive Summary

SmartCivic+ is an AI-powered, spatial-first civic infrastructure governance and defect resolution platform. It bridges citizens, municipal field repair crews (workers), and municipal administration (officers).

---

## 2. System Architecture & Module Categorization

### A. CORE MODULES (Essential & Operational)

1. **Authentication & Role-Based Access Control (RBAC)**
   - **Intended Behavior:** Secure registration, bcrypt password hashing, HttpOnly JWT access/refresh token generation, and strict role enforcement (`citizen`, `worker`, `officer`).
   - **Backend:** `routes/auth.py`, `models/user.py`
   - **Frontend:** `templates/auth/login.html`, `templates/auth/register.html`
   - **Database:** `users` collection

2. **Citizen Complaint Reporting & Verification System**
   - **Intended Behavior:** Multi-lingual complaint filing, interactive Leaflet map pin placement, Nominatim reverse geocoding, MIME photo upload, emergency category declaration, crowd confirmation, resolution feedback, and reopening loop.
   - **Backend:** `routes/api/issues.py`, `services/complaint_service.py`
   - **Frontend:** `static/js/citizen.js`, `templates/citizen/dashboard.html`, `templates/report_issue.html`
   - **Database:** `issues`, `audit_logs` collections

3. **Field Crew (Worker) Operations & GPS Tracking**
   - **Intended Behavior:** Assigned job queue listing, status transitions (`assigned` → `work_started` → `work_completed`), live GPS coordinate updates, and upload of mandatory post-repair resolution proof images.
   - **Backend:** `routes/api/workers.py`, `routes/worker.py`
   - **Frontend:** `static/js/worker.js`, `templates/worker/dashboard.html`
   - **Database:** `users`, `issues`, `assignments` collections

4. **Officer Command & Worker Assignment Engine**
   - **Intended Behavior:** Real-time citywide issue dashboard, automated & manual worker recommendation scoring algorithm (distance, skill match, workload capacity, SLA compatibility), review overrides, rejection handling, and officer verification closure.
   - **Backend:** `routes/officer.py`, `routes/api/issues.py`, `routes/api/workers.py`, `services/assignment_service.py`
   - **Frontend:** `static/js/dashboard.js`, `templates/officer/dashboard.html`
   - **Database:** `issues`, `assignments`, `users` collections

5. **GIS Spatial Analytics & Route Engine**
   - **Intended Behavior:** Interactive Leaflet maps rendering issue markers, severity heatmaps, worker live locations, OSRM road routing navigation, ward health scores, and predictive defect hotspots.
   - **Backend:** `routes/api/map.py`, `services/route_service.py`, `services/prediction_service.py`
   - **Frontend:** `static/js/map.js`, `static/js/dashboard.js`
   - **Database:** `issues`, `clusters`, `infrastructure_assets` collections

---

### B. SUPPORTING MODULES

1. **AI Automated Triage & Computer Vision**
   - **Intended Behavior:** Complaint description analysis (category, type, severity, department) using Gemini API with fallback rule-based NLP, computer vision image severity evaluation, and AI Copilot query answering.
   - **Backend:** `services/ai_service.py`, `services/ai_evaluation_service.py`, `routes/api/analytics.py`

2. **Service Level Agreement (SLA) & Escalation Service**
   - **Intended Behavior:** Automated SLA target assignment based on severity, status sweeps for breach detection, and automated notifications to citizens and officers.
   - **Backend:** `services/sla_service.py`, `models/sla.py`

3. **Notifications & Real-Time Socket.IO Messaging**
   - **Intended Behavior:** In-app notification creation, unread count tracking, single/bulk read endpoints, and real-time Socket.IO room events (`user_{id}`, `ward_{ward}`, `role_officer`).
   - **Backend:** `services/notification_service.py`, `routes/api/notifications.py`, `app.py`

4. **Analytics, PDF Report & Copilot Intelligence**
   - **Intended Behavior:** Overview statistics, ward health calculations, department metrics, weekly intelligence PDF report generation via ReportLab, and AI Copilot natural language Q&A.
   - **Backend:** `routes/api/analytics.py`, `services/report_service.py`

---

### C. OPTIONAL / ADVANCED MODULES

1. **CivicPulse Infrastructure Predictive Simulation**
   - **Intended Behavior:** Predictive simulations for adding field workers or shifting category priorities on ward health scores.
   - **Backend:** `routes/api/simulation.py`, `routes/api/civicpulse.py`, `services/simulation_service.py`

2. **Public Transparency Portal**
   - **Intended Behavior:** Open public access portal displaying non-sensitive city infrastructure stats, closed issue counts, and live public defect map.
   - **Backend:** `routes/public.py`, `templates/public/transparency.html`

---

### D. MOCK / PLACEHOLDER CLASSIFICATION

- **Legacy AI Standalone Scripts:** `docs/legacy/ai_unused/` contains legacy standalone experiments that are disabled and preserved for reference. Production AI uses unified `services/ai_service.py`.
- **Zero Mock Policy:** All production backend endpoints, map operations, worker routes, and database operations execute against real MongoDB data and active services.

---

## 3. End-to-End Core Workflow Verification

```
[Resident] Files Complaint + Map Pin + Image
    ↓
[API] Validates MIME/size + Inserts MongoDB Document
    ↓
[AI Triage] Computes Category, Severity & SLA Target
    ↓
[Officer Dashboard] Displays Complaint & Auto-Recommends Workers
    ↓
[Officer] Assigns Field Crew (Worker)
    ↓
[Worker Dashboard] Receives Job Notification + Views Map Location
    ↓
[Worker] Starts Repair + Updates GPS + Uploads Proof Photo
    ↓
[Citizen & Officer] Verification & Closure
    ↓
[System] Updates Citizen CivicScore + Recalculates Ward Health
```
