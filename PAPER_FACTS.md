# SmartCivic: Empirical Evaluation & Paper Facts

This document compiles every citable empirical number, model evaluation, system benchmark, and concrete verification result from the codebase for academic citation.

---

## 1. Machine Learning & Computer Vision Evaluation

### Road Defect Detector (YOLOv8n ONNX)
- **Model Checksum (SHA-256):** `07d9464095daad753d2b66f02e11a08a8b13537b77920f7692603bdefef11b08`
- **File & Size:** `ml/models/road_damage_v1.onnx` (12,678,126 bytes / 12.68 MB)
- **Input Dimensions:** `[1, 3, 416, 416]` (RGB float32 normalized 0.0–1.0)
- **Output Tensor:** `[1, 7, 3549]` (4 bounding box coordinates + 3 class scores)
- **Dataset Configuration:** `ml/datasets/work/data.yaml`
  - Class IDs & Names: `0: 'Crack'`, `1: 'Pothole'`, `2: 'Surface Erosion'`
- **Evaluation Split:** `ml/datasets/work/test/images` (159 images)
- **Negative Sample Breakdown:**
  - Positive defect images: **159**
  - Clean-road negative images in frozen test split: **0** (No clean-road negative images exist in the test split; all 159 images contain positive ground-truth defect annotations).
- **Execution Hardware:**
  - **CPU:** 12th Gen Intel(R) Core(TM) i5-1235U (10 physical cores, 12 logical processors)
  - **RAM:** 7.68 GB (8,245,329,920 bytes)
- **CPU Inference Latency:**
  - **Mean:** `16.56 ms`
  - **P95:** `18.43 ms`
- **Direct ONNX Re-Evaluation Metrics (`results/onnx_direct_eval.log`):**
  - **Overall mAP@50:** `0.3962` (39.62%)
  - **Pothole (`1`):** AP@50 = `0.4266`, Precision@0.25 = `0.7209`, Recall@0.25 = `0.2952`, N_GT = 105
  - **Surface Erosion (`2`):** AP@50 = `0.5432`, Precision@0.25 = `0.7778`, Recall@0.25 = `0.5738`, N_GT = 61
  - **Crack (`0`):** AP@50 = `0.2188`, Precision@0.25 = `0.7500`, Recall@0.25 = `0.0811`, N_GT = 74
- **Historical Ultralytics val Metrics (`ml/reports/road_detector_evaluation.json`):**
  - Overall mAP@50: `0.3999` (39.99%)
  - Overall mAP@50-95: `0.1756` (17.56%)
  - Overall Precision: `0.4188`, Overall Recall: `0.4265`

### Local Text Classifier (TF-IDF + SGDClassifier)
- **Model Checksum (SHA-256):** `a645cf4ae3d763572cceef39be5f9ce1d519cef0d4b1511b7a54ac0b58662687`
- **File & Size:** `models_artifacts/text_classifier_v1.joblib` (65,471 bytes / 65.5 KB)
- **Benchmark:** 66 diverse real-world Bengaluru municipal complaints (English, Kannada, Hinglish)
- **Source:** `audit_tmp/audit_ai_routing_engine.py` (COMPLAINT_TEST_SET)
- **Top-1 Categorization Accuracy:** `42.42%` (28/66 exact service matches in offline mode)
- **CPU Inference Latency:** Mean: `18.83 ms`, P95: `21.14 ms`

### Emergency Detection
- **Benchmark Type:** **Development benchmark, tuned on, NOT a holdout**
- **File:** `audit_tmp/bench_emergency.py`
- **Case Breakdown:** Total = 20 (Emergency Cases: 17, Benign Cases: 3)
- **Development Recall:** `100.0%` (17/17 critical emergency cases detected)
- **Development Precision:** `100.0%` (0 false alarms across the 3 benign cases)
- **Holdout Status:** `data/holdout_emergency.csv` does **NOT** exist in the repository. No tuning has been or will be performed on external holdout files.

---

## 2. CEFAP Prioritization Pipeline

Evaluated across 50 diverse municipal scenario distributions (`results/cefap_ablation.json`):

| Model Baseline | Architecture / Configuration | Mean CIPS Score | Std CIPS | Min CIPS | Max CIPS |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **M1** | Text Severity Only (Single-signal baseline) | 0.6150 | 0.2793 | 0.2500 | 1.0000 |
| **M2** | Text + Image Average (Uncalibrated multi-modal) | 0.6775 | 0.2575 | 0.3750 | 1.0000 |
| **M3** | Text + Image + Location (Fixed weight heuristics) | 0.4794 | 0.1516 | 0.3200 | 0.7200 |
| **M4** | All 6 Signals without Reliability Factor | 0.4480 | 0.1270 | 0.2050 | 0.6900 |
| **M5** | **Full CEFAP with Evidence Reliability Damping** | **0.2626** | **0.0727** | **0.1130** | **0.3790** |

*Note: Mean CIPS is a distribution score metric reflecting priority dampening, NOT an accuracy or calibration metric. Human annotation evaluation is supported via `results/cefap_label_sheet.csv` and `scripts/eval_cefap_agreement.py`.*

---

## 3. System Runtime & Performance

Measured on Windows x64 Python 3.10.11:
- **Application Cold Start Time:** `182.91 ms` (`results/system_performance.json`)
- **Process Resident Set Size (RSS):** `86.60 MB` (base), `189.87 MB` (with active ONNX session)
- **GET `/api/health` Latency:** Mean: `2.13 ms`, P95: `2.09 ms`
- **GET `/api/map/issues` Latency:** Mean: `1.69 ms`, P95: `2.25 ms`

---

## 4. Security Verification

- **Default-Deny URL Authorization:** 100% of routes protected or in explicit canonical public allowlist (`test_default_deny.py`).
- **Authorization Matrix:** Complete coverage across all 5 roles (`test_authz_matrix.py`).
- **Upload Attack Rejection:** 100% rejection rate for disguised PHP (`.php.jpg`), path traversal filenames, disguised SVGs, and payloads > 8MB (`test_stage1_attack_uploads.py`).
- **Working Tree Secret Scan:** `detect-secrets` scan completed (`results/detect_secrets_scan.json`).
- **Vulnerability Audit:** `pip-audit` report archived (`results/pip_audit_report.txt`).

---

## 5. Items NOT Supported / NOT Run (BLOCKED)

The following items are explicitly marked as NOT supported, non-existent, or blocked:
1. **Real Bengaluru Photos Benchmark (`data/real_photos/`):** **BLOCKED / NOT RUN** — Directory `data/real_photos/` and `data/real_photos/labels.csv` do not exist in the repository. Driver script provided in `scripts/eval_real_photos.py`.
2. **Untouched Emergency Holdout (`data/holdout_emergency.csv`):** **NOT SUPPORTED** — File does not exist. Existing emergency metrics derive strictly from the 20-case development tuning suite.
3. **Automated Human Label Generation:** **NOT SUPPORTED** — Human labels must be supplied manually by external annotators in `results/cefap_label_sheet.csv` and evaluated via `scripts/eval_cefap_agreement.py`.
4. **OWASP ZAP Baseline via Docker:** **BLOCKED** — Docker daemon is not running on the local Windows host (`open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified`).
