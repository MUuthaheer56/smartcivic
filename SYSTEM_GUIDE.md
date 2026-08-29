# SmartCivic V2.0 — System Usage, Functions & UI Guide

This guide describes the directory structure, file locations, core functions, API endpoints, user interfaces, and execution guidelines for the SmartCivic V2.0 platform.

---

## 1. Codebase Directory Map

The core implementation files are organized as follows:

```
smartcivic/
├── app.py                     # Flask application factory, blueprint registrations, index configuration
├── run.py                     # Development server entry point
├── config.py                  # Environment-backed configuration properties
├── test_app.py                # Comprehensive unit testing suite (71 assertions)
├── ai/                        # Modular AI and intelligence package
│   ├── __init__.py            # Package initializer
│   ├── image_analyzer.py      # Pillow image quality check and visual severity scorer
│   ├── nlp_classifier.py      # Weighted keyword NLP triage categorizer
│   ├── drain_predictor.py     # Monsoon drainage flood risk forecaster (OpenWeatherMap-backed)
│   ├── trust_scorer.py        # Ward-level civic trust score calculator
│   ├── noise_validator.py     # Decibel limit validator against India CPCB noise rules
│   └── anomaly_detector.py    # Rolling Z-score spike detector for category reporting rates
├── routes/                    # API Routing Blueprints
│   ├── ai_routes.py           # Blueprint for /api/ai/* endpoints
│   ├── issues.py              # Blueprint for /api/issues/* and /api/complaints/* (noise recording)
│   ├── pages.py               # Blueprint for webpage route templates (/ai-insights)
│   └── dashboard.py           # Blueprint for /api/dashboard/* endpoints
├── services/                  # Business Logic Services
│   ├── scheduler_service.py   # Background scheduler utilizing APScheduler (replaces inline triggers)
│   ├── sla_service.py         # Ticket SLA duration and breach trackers
│   └── route_optimizer.py     # Weighted Nearest Neighbor TSP worker route planner
├── static/                    # Frontend Styles & Scripts
│   ├── css/
│   │   ├── main.css           # Design tokens, mobile navbar responsive styling
│   │   └── ai.css             # AI panel widget styling
│   └── js/
│     ├── main.js              # Auth status, socket listeners, mobile hamburger toggle
│     ├── report.js            # Category suggestions, geolocation detection, Web Audio mic recorder
│     └── ai_panel.js          # Widget renderer for trust scores, anomalies, and drain risks
└── templates/                 # Jinja2 HTML Templates
    ├── base.html              # Layout skeleton containing the mobile menu toggle
    ├── report_issue.html      # Issue report form with inline noise recording widget
    └── ai_insights.html       # Authority AI Hub dashboard
```

---

## 2. Core Python Functions

### Image Quality Gate & Sharpness Analysis
*   **Location:** `ai/image_analyzer.py` -> `analyze_image(image_bytes: bytes) -> dict`
*   **Working:** Re-saves uploaded bytes to strip EXIF data. Calculates the mean grayscale pixel level (luminance) and sharpness via pixel variance after Gaussian blurring.
*   **Usage Example:**
    ```python
    from ai.image_analyzer import analyze_image
    with open("evidence.jpg", "rb") as f:
        result = analyze_image(f.read())
    print(result) # returns {"passed": True, "sharpness": 120.4, "luminance": 85.2, ...}
    ```

### NLP Classification & Urgency Flagging
*   **Location:** `ai/nlp_classifier.py` -> `classify_issue(title: str, description: str = "") -> dict`
*   **Working:** Tokenizes and matches descriptions against weighted keyword lists for `pothole`, `garbage`, `streetlight`, `water`, `sewage`, `noise`, `animals`, and `construction`.
*   **Usage Example:**
    ```python
    from ai.nlp_classifier import classify_issue
    res = classify_issue("water pipe burst", "water is leaking all over the street")
    # res = {"category": "water", "department": "BWSSB Water Supply", "confidence_score": 0.85, ...}
    ```

### Civic Trust Index Calculations
*   **Location:** `ai/trust_scorer.py` -> `compute_trust_score(community_id: str) -> dict`
*   **Working:** Aggregates SLA compliance (40%), resolution rate (25%), voter participation (20%), and 30-day recurrence rate (15%) to calculate a score from 0 to 100.
*   **Usage Example:**
    ```python
    from ai.trust_scorer import compute_trust_score
    score_details = compute_trust_score("660000000000000000000001")
    ```

---

## 3. API Routing Specifications

| Method | Endpoint | Auth | Request Body/Params | Description |
| :--- | :--- | :--- | :--- | :--- |
| **POST** | `/api/ai/analyze-image` | Verified | Multipart File: `image` | Returns quality gate passes and visual severity. |
| **POST** | `/api/ai/classify-text` | Verified | JSON: `{"title": "...", "description": "..."}` | Returns suggested category and department. |
| **GET** | `/api/ai/drain-risk/<community_id>`| Authority | None | Returns proximity-based drainage flood risk warnings. |
| **GET** | `/api/ai/trust-score/<community_id>`| Auth | None | Returns ward level Civic Trust Index breakdown. |
| **GET** | `/api/ai/anomalies/<community_id>` | Authority | Query param: `lookback_days` | Detects category report spikes using Z-scores. |
| **POST** | `/api/ai/validate-noise` | Verified | JSON: `{"db_spl": 65, "zone_type": "residential", "is_night": false}` | Evaluates dB measurements against India CPCB limits. |
| **GET** | `/api/issues/suggest-category` | Open | Query params: `title`, `description` | Suggestions powered by V2.0 NLP engine. |

---

## 4. User Interfaces & Working Mechanisms

### A. AI Intelligence Hub Dashboard (`/ai-insights`)
*   **Access:** Limited to users with the `authority` role. Accessed via the `🧠 AI Hub` button in the navbar.
*   **Layout:**
    1.  **Civic Trust Score Widget:** Displays the ward's performance grade (A to D) using a conic-gradient progress ring, alongside compliance rates.
    2.  **Reporting Anomalies Card:** Lists categories showing abnormal report spikes using dynamic coloring (Red for HIGH Z-score, Amber for MEDIUM).
    3.  **Monsoon Drainage Warnings:** Shows a list of local drains with warning progress bars, highlighting severe blockage risks.
    4.  **Noise Level Validator Sandbox:** A manual input sandbox tool that lets admins quickly test compliance of dB readings.

### B. Citizen Noise Recording Meter
*   **Access:** Integrated on the issue reporting form (`/report`). Displays only when selecting **Noise Pollution** as the issue category.
*   **Working:**
    1.  Uses `getUserMedia()` to gain access to the device microphone.
    2.  Sets up an `AudioContext` and `AnalyserNode` to sample time-domain floating-point audio data.
    3.  Calculates the Root Mean Square (RMS) value of the buffer:
        $$\text{RMS} = \sqrt{\frac{1}{M} \sum_{i=1}^{M} v_i^2}$$
    4.  Converts the RMS value to decibel Sound Pressure Level (dB SPL):
        $$\text{dB SPL} = 20 \log_{10}\left(\frac{\text{RMS}}{20\mu\text{Pa}}\right)$$
    5.  Displays live decibel values (color-coded green, yellow, or red based on severity).
    6.  On stop, records the peak dB value, calls the backend validation API, and updates hidden form elements to document compliance.

### C. Mobile Navigation Hamburger Menu
*   **Access:** Displays automatically on viewport widths smaller than `768px`.
*   **Working:** Replaces the standard horizontal navigation link block with a hamburger button. Clicking toggles the `.open` class on `#nav-links`, rendering links vertically over content with glassmorphic backing.

---

## 5. Running the Tests & Dev Server

### Run the Unit Tests
To run all 71 tests validating serialization, SLA timings, Nearest Neighbor TSP, reputation levels, NLP rules, image quality gates, noise limits, and anomaly statistics:
```powershell
.venv\Scripts\python -m unittest test_app.py -v
```

### Run the Development Server
To launch the Flask development server on port 5000:
```powershell
.venv\Scripts\python run.py
```
*Note: The background scheduler service will automatically initialize on startup and print `[Scheduler] Background scheduler started.` inside the logs.*
