# SmartCivic: Pre-Submission Verification & Final Status Report

**Branch:** `release/paper-final`  
**Base Commit:** Created directly from `fix/ui-repair` commit `db75332`  
**Execution Environment:** Windows 11, PowerShell, Python 3.10.11, Intel Core i5-1235U, 8GB RAM, MongoDB 127.0.0.1:27017 (`smartcivic`)  
**Status:** **READY FOR PAPER SUBMISSION**

---

## 1. Item-by-Item Verification & Evidence

### Item 1: Branch Lineage & Commit History
- **Status:** **FIXED**
- **Evidence:** `git log --oneline --graph --decorate -40` confirms that `release/paper-final` branches off `fix/ui-repair` (`db75332`) and incorporates all prior fix branches:
  - `fix/pre-release` (`6ff7063`, `d35cfc8`, `745951f`)
  - `fix/phase-8` (`123d71e`)
  - `fix/phase-7` (`533e2b8`)
  - `fix/phase-6` (`b7edbb0`)
  - `fix/phase-5` (`bf82c05`)
  - `fix/phase-4` (`a088175`)
  - `fix/phase-3` (`ea5defa`)
  - `fix/phase-2` (`3be0b8d`)
  - `fix/phase-1` (`a2db3e8`, `e413a01`)

### Item 2: State Transitions & Proof Enforcements
- **Status:** **FIXED**
- **Evidence:**
  - `git diff db75332..HEAD -- constants/states.py services/verification_service.py` reveals two changes:
    1. In `constants/states.py`, `assigned` in `LEGAL_TRANSITIONS` was aligned with `ROLE_TRANSITIONS["worker"]` to permit direct transition to `work_completed` when the worker submits a repair photo.
    2. In `services/verification_service.py`, `update_status(..., actor_role="worker")` was passed explicitly so the state machine validates worker permissions.
  - **Integrity Confirmation:**
    - **No citizen bypass:** Citizens remain strictly forbidden from marking issues as `work_completed`, `resolved`, or `closed` (`services/complaint_service.py:614-615`).
    - **No worker proof skip:** The route `/api/issues/<id>/resolve` strictly mandates an upload file (`request.files.get('after_image') or request.files.get('image')`) and returns `400` if absent (`routes/api/issues.py:1150-1155`).
  - **Test Assertions Check:** All 200 unit/integration tests and 6 E2E Playwright tests pass without a single security assertion loosened or removed.

### Item 3: Road Damage Detector Evaluation
- **Status:** **FIXED**
- **Evidence:**
  - Fresh direct evaluation of shipped ONNX model `ml/models/road_damage_v1.onnx` executed via `scripts/eval_onnx_direct.py`.
  - Log saved to `results/onnx_direct_eval.log` and structured results in `results/detector_eval.json`.
  - **Dataset YAML (`ml/datasets/work/data.yaml`):**
    - `nc: 3`
    - Class IDs: `0: 'Crack'`, `1: 'Pothole'`, `2: 'Surface Erosion'`
  - **Clean Road Negatives:** `0` clean-road negative images exist in the frozen test set; all 159 images contain positive defect bounding boxes.
  - **Hardware:** Intel Core i5-1235U (10 cores, 12 threads), 7.68 GB RAM.
  - **Latency:** Mean `16.56 ms`, P95 `18.43 ms`.
  - **Metrics Comparison:**
    - Fresh Direct ONNX run: mAP@50 = `0.3962`
    - Historical Ultralytics val report: mAP@50 = `0.3999`, mAP@50-95 = `0.1756`

### Item 4: Emergency Detection Relabeling
- **Status:** **FIXED**
- **Evidence:**
  - Relabeled everywhere as **"development benchmark, tuned on, NOT a holdout"** in `results/emergency_eval.json`, `PAPER_FACTS.md`, and `FINAL_REPORT.md`.
  - Case breakdown documented: 17 emergency cases, 3 benign cases.
  - `data/holdout_emergency.csv` does not exist; no tuning has been performed on any external holdout data.

### Item 5: CEFAP Evaluation Framework & Human Label Sheet
- **Status:** **FIXED**
- **Evidence:**
  - Ceased calling mean CIPS an accuracy or calibration metric.
  - Created `results/cefap_label_sheet.csv` containing 60 municipal scenario descriptions with shuffled IDs, zero priority hints, zero scores, and empty labeler columns.
  - Implemented `scripts/eval_cefap_agreement.py` calculating tier agreement (%), weighted Cohen's Kappa, Spearman rho, and high-priority (P0/P1) recall against human labels.

### Item 6: Security Verification
- **Status:** **PARTIAL**
  - **Secret Scanning (detect-secrets):** **FIXED** — Installed `detect-secrets` v1.5.0 and ran full working-tree scan (`results/detect_secrets_scan.json`).
  - **Dependency Vulnerability Audit (pip-audit):** **FIXED** — Ran `pip-audit` and saved full text report to `results/pip_audit_report.txt` (5,684 characters) capturing known package CVEs.
  - **OWASP ZAP Baseline via Docker:** **BLOCKED** — Docker daemon is not running on the Windows host (`open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified`).

### Item 7: Real Photos Evaluation Script
- **Status:** **BLOCKED / NOT RUN**
- **Evidence:**
  - Written `scripts/eval_real_photos.py` to evaluate `data/real_photos/labels.csv` reporting per-photo hit, miss, false alarm, and failure filenames.
  - Safely stops when the directory does not exist:
    ```
    [STATUS: BLOCKED / NOT RUN] Directory '...\data\real_photos' does not exist.
    ```

### Item 8: Publication Hygiene & Paper Facts
- **Status:** **FIXED**
- **Evidence:** Created and updated `MODEL_CARD.md`, `DATA.md`, `PAPER_FACTS.md`, and `FINAL_REPORT.md` documenting all verified numbers and unsupported/blocked items.

### Item 9: Complete Test Suite & Playwright Role Smoke Run
- **Status:** **FIXED**
- **Evidence:**
  - Pytest: `python -m pytest --ignore=tests/e2e -q` &rarr; **200 passed in 37.58s**
  - Playwright: `python -m pytest tests/e2e/test_smoke.py -v -s` &rarr; **6 passed in 91.35s**

---

## 2. Playwright Per-Role Smoke Verification Table

| Role / Fixture | Pages Navigated | Console Errors | Network 4xx/5xx | Loading Spinners > 8s | Status |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **admin** | `/dashboard`, `/analytics`, `/issues`, `/map` | 0 | 0 | 0 | **PASSED** |
| **officer_all** | `/dashboard`, `/issues`, `/map`, `/analytics` | 0 | 0 | 0 | **PASSED** |
| **officer_ward** | `/dashboard`, `/issues`, `/map`, `/analytics` | 0 | 0 | 0 | **PASSED** |
| **worker** | `/dashboard`, `/worker/tasks`, `/map` | 0 | 0 | 0 | **PASSED** |
| **citizen_verified** | `/dashboard`, `/report`, `/issues`, `/map`, `/citizen/profile` | 0 | 0 | 0 | **PASSED** |
| **citizen_pending** | `/citizen/verify-ward`, `/dashboard`, `/issues` | 0 | 0 | 0 | **PASSED** |
