# SmartCivic: Empirical Data Sheet, Benchmarks & Mathematical Formulations

This document aggregates every citable empirical number, model weight checksum, dataset breakdown, latency distribution, ablation metric, and mathematical formulation implemented and measured in the SmartCivic repository.

---

## 1. Machine Learning & Computer Vision Specifications

### 1.1 Road Surface Defect Detector (YOLOv8n ONNX)
- **Model Checksum (SHA-256):** `07d9464095daad753d2b66f02e11a08a8b13537b77920f7692603bdefef11b08`
- **File Artifact & Size:** `ml/models/road_damage_v1.onnx` ($12,678,126\text{ bytes} \approx 12.68\text{ MB}$)
- **Architecture Base:** Ultralytics YOLOv8n (Nano) compiled to ONNX Runtime
- **Input Dimensions:** `[1, 3, 416, 416]` (RGB float32 normalized in range $[0.0, 1.0]$)
- **Output Tensor:** `[1, 7, 3549]` (4 spatial coordinates + 3 class scores across 3549 anchor candidates)
- **Dataset Configuration:** `ml/datasets/work/data.yaml`
  - Number of Classes ($nc$): 3
  - Class Mappings:
    - `0`: `'Crack'`
    - `1`: `'Pothole'`
    - `2`: `'Surface Erosion'`
- **Evaluation Split:** `ml/datasets/work/test/images` (159 total images)
- **Negative Sample Breakdown:**
  - Positive defect images: **159**
  - Clean-road negative images in frozen test split: **0** (All 159 images contain positive ground-truth bounding boxes)
- **Execution Hardware Profile:**
  - **CPU:** 12th Gen Intel(R) Core(TM) i5-1235U (10 physical cores, 12 logical threads, base frequency 1.30 GHz)
  - **RAM:** 7.68 GB physical memory (8,245,329,920 bytes)
  - **OS / Runtime:** Windows 11 x64, Python 3.10.11, onnxruntime 1.20.1
- **CPU Inference Latency:**
  - **Mean:** $\mathbf{16.56\text{ ms}}$
  - **P95:** $\mathbf{18.43\text{ ms}}$
  - **P99:** $\mathbf{21.12\text{ ms}}$
- **Direct ONNX Re-Evaluation Metrics (`results/onnx_direct_eval.log`):**
  - **Overall mAP@50:** $\mathbf{0.3962}$ ($39.62\%$)
  - **Pothole (`1`):** AP@50 = $0.4266$, Precision@0.25 = $0.7209$, Recall@0.25 = $0.2952$, $N_{\text{GT}} = 105$
  - **Surface Erosion (`2`):** AP@50 = $0.5432$, Precision@0.25 = $0.7778$, Recall@0.25 = $0.5738$, $N_{\text{GT}} = 61$
  - **Crack (`0`):** AP@50 = $0.2188$, Precision@0.25 = $0.7500$, Recall@0.25 = $0.0811$, $N_{\text{GT}} = 74$
- **Historical Ultralytics val Metrics (`ml/reports/road_detector_evaluation.json`):**
  - Overall mAP@50: $0.3999$ ($39.99\%$)
  - Overall mAP@50-95: $0.1756$ ($17.56\%$)
  - Overall Precision: $0.4188$, Overall Recall: $0.4265$

### 1.2 Local Vernacular Text Classifier (TF-IDF + SGDClassifier)
- **Model Checksum (SHA-256):** `a645cf4ae3d763572cceef39be5f9ce1d519cef0d4b1511b7a54ac0b58662687`
- **File Artifact & Size:** `models_artifacts/text_classifier_v1.joblib` ($65,471\text{ bytes} \approx 65.5\text{ KB}$)
- **Vocabulary Size:** 1,248 unigrams and bigrams
- **Benchmark Corpus:** 66 diverse real-world Bengaluru municipal complaints (English, Kannada, Hinglish)
- **Top-1 Categorization Accuracy:** $\mathbf{42.42\%}$ (28/66 exact service matches in fully disconnected offline mode)
- **CPU Inference Latency:** Mean: $\mathbf{18.83\text{ ms}}$, P95: $\mathbf{21.14\text{ ms}}$

### 1.3 Emergency Heuristic Detection Benchmark
- **Benchmark Specification:** **Development benchmark, tuned on, NOT a holdout** (`audit_tmp/bench_emergency.py`)
- **Total Test Cases:** 20 municipal reports
  - Emergency Cases: 17
  - Benign Routine Cases: 3
- **Development Recall:** $\mathbf{100.0\%}$ (17/17 critical emergency cases detected)
- **Development Precision:** $\mathbf{100.0\%}$ (0 false alarms across the 3 benign cases)
- **Holdout Status:** `data/holdout_emergency.csv` does **NOT** exist in the repository. No tuning has been performed on external holdout files.

---

## 2. CEFAP Prioritization Pipeline & Ablation Data

Evaluated across 50 diverse municipal scenario distributions (`results/cefap_ablation.json`):

| Model Baseline | Architecture / Configuration | Mean CIPS Score | Std CIPS | Min CIPS | Max CIPS |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **M1** | Text Severity Only (Single-signal baseline) | 0.6150 | 0.2793 | 0.2500 | 1.0000 |
| **M2** | Text + Image Average (Uncalibrated multi-modal) | 0.6775 | 0.2575 | 0.3750 | 1.0000 |
| **M3** | Text + Image + Location (Fixed weight heuristics) | 0.4794 | 0.1516 | 0.3200 | 0.7200 |
| **M4** | All 6 Signals without Reliability Factor | 0.4480 | 0.1270 | 0.2050 | 0.6900 |
| **M5** | **Full CEFAP with Evidence Reliability Damping** | **0.2626** | **0.0727** | **0.1130** | **0.3790** |

*Note on Metric Interpretation:* Mean CIPS is a distribution score metric reflecting priority dampening, NOT an accuracy or calibration metric. Human annotation evaluation is supported via `results/cefap_label_sheet.csv` and `scripts/eval_cefap_agreement.py`.

---

## 3. Mathematical Formulations

### 3.1 Composite Issue Prioritization Score (CIPS)
For a municipal issue report $r$:
$$S_{\text{raw}} = \sum_{k=1}^{6} w_k \cdot \sigma_k$$
$$\sum_{k=1}^6 w_k = 1.0, \quad w = [0.25, 0.25, 0.15, 0.15, 0.10, 0.10]$$

$$\mathcal{R}_{\text{evidence}} = \alpha \cdot \mathbb{I}(I \neq \emptyset) + \beta \cdot \text{Conf}(I) + \gamma \cdot \text{GeoValid}(\mathbf{x})$$
$$\alpha = 0.40, \quad \beta = 0.40, \quad \gamma = 0.20$$

$$S_{\text{CIPS}} = S_{\text{raw}} \cdot \mathcal{R}_{\text{evidence}}$$

### 3.2 Spatiotemporal Geodesic Haversine Distance
$$D_H(\mathbf{x}_1, \mathbf{x}_2) = 2 R \arcsin\left(\sqrt{\sin^2\left(\frac{\phi_2 - \phi_1}{2}\right) + \cos\phi_1\cos\phi_2\sin^2\left(\frac{\lambda_2 - \lambda_1}{2}\right)}\right)$$
$$R = 6371\text{ km}, \quad D_H \le 0.050\text{ km} \; (50\text{ meters})$$

### 3.3 Perceptual Gradient Hash (dHash)
Image is downsampled to $9 \times 8$ grayscale matrix $P$. Difference bit string $H$:
$$H(i, j) = \begin{cases} 1 & \text{if } P(i, j) > P(i, j+1) \\ 0 & \text{otherwise} \end{cases} \quad \forall \; i \in [0, 7], \; j \in [0, 7]$$
$$\text{Hamming}(H_1, H_2) = \sum_{b=1}^{64} (H_1^{(b)} \oplus H_2^{(b)}) \le 10$$

### 3.4 SLA Exponential Decay Impedance
$$S_{\text{decay}}(t) = 1.0 - \exp\left(-\frac{t - t_{\text{created}}}{\tau_{\text{SLA}}}\right)$$
where $\tau_{\text{SLA}}$ is calibrated per category (e.g., Roads = 72 hours, Water = 24 hours, Streetlights = 48 hours).

### 3.5 Citizen CivicScore Reputation Decay
When a citizen report is resolved and verified:
$$\Delta C = +5 \cdot \text{Conf}(I)$$
When a report is flagged as malicious, fraudulent, or rejected:
$$\Delta C = -15$$
Current CivicScore:
$$C_t = \max(10, \min(100, C_{t-1} + \Delta C))$$
$$S_{\text{civic}} = \frac{C_t}{100.0}$$

---

## 4. System Runtime & Performance Benchmarks

Measured on Windows x64 Python 3.10.11 host (`results/system_performance.json`):
- **Application Cold Start Latency:** $\mathbf{182.91\text{ ms}}$
- **Base Memory Footprint (Resident Set Size):** $\mathbf{86.60\text{ MB}}$
- **Active ONNX Inference Memory Footprint:** $\mathbf{189.87\text{ MB}}$
- **Micro-Benchmark Endpoint Latency:**
  - `GET /api/health`: Mean: $\mathbf{2.13\text{ ms}}$, P95: $\mathbf{2.09\text{ ms}}$
  - `GET /api/map/issues`: Mean: $\mathbf{1.69\text{ ms}}$, P95: $\mathbf{2.25\text{ ms}}$
  - `POST /api/issues`: Mean: $\mathbf{24.8\text{ ms}}$ (including disk I/O, dHash, and database indexing)

---

## 5. Security & Threat Mitigation Metrics

- **Default-Deny URL Authorization:** $\mathbf{100.0\%}$ of routes protected or in explicit canonical public allowlist (`test_default_deny.py`).
- **Authorization Matrix:** Complete coverage across all 5 roles (`test_authz_matrix.py`).
- **Upload Attack Rejection:** $\mathbf{100.0\%}$ rejection rate for disguised PHP (`.php.jpg`), path traversal filenames, disguised SVGs, and payloads $>8\text{MB}$ (`test_stage1_attack_uploads.py`).
- **Automated Secret Scanning:** Full repository scanned with `detect-secrets` v1.5.0 (`results/detect_secrets_scan.json`).
- **Vulnerability Audit:** Python dependencies scanned via `pip-audit` (`results/pip_audit_report.txt`).

---

## 6. Full Test Suite Execution Summary

- **Total Test Cases:** **233**
- **Passed:** **233**
- **Failed:** **0**
- **Errors:** **0**
- **Skipped:** **0**
- **Total Duration:** $190.44\text{ seconds}$
- **Sub-Suites:**
  - Unit & Integration: 220 tests
  - Playwright Multi-Role Smoke & Actions: 13 tests across 6 user roles (Admin, Officer ALL, Ward Officer, Worker, Verified Citizen, Pending Citizen).
