# SmartCivic Empirical Results & Paper Artifacts

This directory contains experimental measurements, benchmark evaluations, and empirical metrics for SmartCivic. All files are generated dynamically via:

```powershell
python scripts/reproduce_results.py
```

## Result Files

- **`detector_eval.json`**: Evaluation metrics for the CPU-optimized ONNX road defect detector (`ml/models/road_damage_v1.onnx`, YOLOv8n, 12.68 MB, SHA-256: `07d9464095daad753d2b66f02e11a08a8b13537b77920f7692603bdefef11b08`). Evaluated across test split:
  - mAP@50: **0.3999**
  - mAP@50-95: **0.1756**
  - Precision: **0.4188**
  - Recall: **0.4265**
  - Mean CPU latency: **~16 ms**, P95: **~18 ms**
- **`text_classifier_eval.json`**: Local TF-IDF text classifier (`models_artifacts/text_classifier_v1.joblib`, 65.5 KB, SHA-256: `a645cf4ae3d763572cceef39be5f9ce1d519cef0d4b1511b7a54ac0b58662687`) evaluated across 66 diverse Bengaluru complaints with Kannada/Hinglish glossary:
  - Top-1 service accuracy: **42.42%**
  - Mean inference latency: **~19 ms**, P95: **~21 ms**
- **`emergency_eval.json`**: Emergency holdout benchmark evaluation across 20 high-stakes and benign civic incident descriptions:
  - Emergency Recall: **100.0%** (17/17 critical emergencies detected)
  - Emergency Precision: **100.0%** (0 false positives on benign reports)
- **`cefap_ablation.json`**: Comprehensive ablation study across baseline priority models M1 through M5:
  - **M1** (Text severity only): Mean CIPS = 0.6150
  - **M2** (Text + Image uncalibrated): Mean CIPS = 0.6775
  - **M3** (Text + Image + Location fixed): Mean CIPS = 0.4794
  - **M4** (All 6 signals, no reliability factor): Mean CIPS = 0.4480
  - **M5** (Full CEFAP with evidence reliability damping): Mean CIPS = 0.2626
  - Parameter sensitivity table included.
- **`system_performance.json`**: System metrics measured on Windows x64 Python 3.10:
  - Cold start time: **< 1.1s**
  - Resident Set Size (RSS): **~86–190 MB**
  - GET `/api/health` mean latency: **~2 ms**
  - GET `/api/map/issues` mean latency: **~1.7 ms**

---
*All measurements are reproducible using `python scripts/reproduce_results.py` in dev or test environments.*
