# SmartCivic: Empirical Evaluation & Paper Facts

This document compiles all empirical numbers, model evaluations, system benchmarks, and architectural facts for citation in the research paper submission.

---

## 1. Machine Learning & Detection Evaluation

### Road Defect Detector (YOLOv8n ONNX)
- **Model Size:** 12.68 MB (12,678,126 bytes)
- **Model Checksum (SHA-256):** `07d9464095daad753d2b66f02e11a08a8b13537b77920f7692603bdefef11b08`
- **Input Dimensions:** `[1, 3, 416, 416]`
- **Classes:** Crack (`D00`), Pothole (`D40`), Surface Erosion (`D20`)
- **Evaluation Split:** 159 held-out images (`ml/datasets/work/test/images/`)
- **mAP@50:** `0.3999` (39.99%)
- **mAP@50-95:** `0.1756` (17.56%)
- **Overall Precision:** `0.4188` (41.88%)
- **Overall Recall:** `0.4265` (42.65%)
- **Per-Class Metrics:**
  - Pothole (`D40`): Precision: `0.416`, Recall: `0.495`, mAP@50: `0.449`, mAP@50-95: `0.153`
  - Surface Erosion (`D20`): Precision: `0.478`, Recall: `0.541`, mAP@50: `0.520`, mAP@50-95: `0.310`
  - Crack (`D00`): Precision: `0.362`, Recall: `0.243`, mAP@50: `0.230`, mAP@50-95: `0.064`
- **CPU Inference Latency:** Mean: `15.91 ms`, P95: `17.92 ms`

### Local Text Classifier (TF-IDF + SGDClassifier)
- **Model Size:** 65.5 KB (65,471 bytes)
- **Model Checksum (SHA-256):** `a645cf4ae3d763572cceef39be5f9ce1d519cef0d4b1511b7a54ac0b58662687`
- **Evaluation Benchmark:** 66 diverse real-world Bengaluru civic complaints (English, Kannada, Hinglish)
- **Top-1 Categorization Accuracy:** `42.42%` (28/66 exact category matches in offline mode)
- **CPU Inference Latency:** Mean: `18.83 ms`, P95: `21.14 ms`

### Emergency Detection (Holdout Benchmark)
- **Evaluation Suite:** 20 verified high-stakes emergencies and benign civic scenarios
- **Emergency Recall:** `100.0%` (17/17 critical emergency cases correctly identified)
- **Emergency Precision:** `100.0%` (0 false alarms triggered on benign non-emergency complaints)

---

## 2. CEFAP Prioritization & Ablation Study

Evaluated across 50 diverse multi-modal test scenarios:

| Model ID | Configuration | Mean CIPS | Std CIPS | Min CIPS | Max CIPS |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **M1** | Text Severity Only (Single Signal) | 0.6150 | 0.2793 | 0.2500 | 1.0000 |
| **M2** | Text + Image Average (Uncalibrated) | 0.6775 | 0.2575 | 0.3750 | 1.0000 |
| **M3** | Text + Image + Location (Fixed Weights) | 0.4794 | 0.1516 | 0.3200 | 0.7200 |
| **M4** | All 6 Signals without Reliability Factor | 0.4480 | 0.1270 | 0.2050 | 0.6900 |
| **M5** | **Full CEFAP with Evidence Reliability Damping** | **0.2626** | **0.0727** | **0.1130** | **0.3790** |

---

## 3. System Runtime & Performance

Measured on Windows x64, Python 3.10.11:
- **Application Cold Start Time:** `182.91 ms` (mean warm application context init: `< 1.1s` including MongoDB index validation)
- **Process Resident Set Size (RSS):** `~86.6 MB` (base), `~189.9 MB` (under multi-model load)
- **GET `/api/health` Latency:** Mean: `2.13 ms`, P95: `2.09 ms`
- **GET `/api/map/issues` Latency:** Mean: `1.69 ms`, P95: `2.25 ms`

---

## 4. Security Verification

- **Default-Deny Authorization Coverage:** `100%` of endpoints inspected via `app.url_map` strictly mapped to canonical public allowlist or protected by auth decorators (`test_default_deny.py`).
- **Authorization Matrix:** Complete role matrix covering citizen, resident, worker, officer, and admin (`test_authz_matrix.py`).
- **Upload Hardening:** 100% rejection rate for disguised PHP shells (`.php.jpg`), disguised SVGs, path traversals, and oversized payloads exceeding 8MB (`test_stage1_attack_uploads.py`).
- **Offline Integrity:** Zero outbound HTTP or socket connections permitted in local AI mode (`test_offline_e2e.py`).
