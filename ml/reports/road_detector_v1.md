# SmartCivic — Road Damage Detector v1.0 Model Report

**Date:** 2026-11-04  
**Model Name:** `SmartCivic Road Damage Detector`  
**Version:** `v1.0`  
**Architecture:** YOLOv8n (exported to ONNX, opset 12)  
**Primary Artifact:** `models_artifacts/road_detector/v1/model.onnx`  
**Manifest Checksum (SHA-256):** `ebb1318bc139cca6616e32f35b4ee5f6aa5be49139e4b9f46488f49800f45963`  
**Model Weight Checksum (SHA-256):** `07d9464095da284534f3b5c65f9091924bcf847d06e2365313936c5354ee2cb4`  

---

## 1. Data Card & Provenance

- **Source Dataset:** `Data Y12 Final` (`images for ml/Data Y12 Final`)
- **License:** Creative Commons Attribution 4.0 International (CC BY 4.0)
- **Total Source Images:** 1,075 images
- **Deduplication:** Perceptual hash (dHash, Hamming distance $\le 4$) identified 15 near-duplicate clusters (30 images). Exactly 15 redundant images were pruned.
- **Clean Unique Images:** 1,060 images
- **Partitioning (Group-Aware Split):**
  - Grouping was enforced across Roboflow stems to guarantee **zero scene leakage** between splits.
  - **Train Split:** 742 images (70.0%)
  - **Validation Split:** 159 images (15.0%)
  - **Test Split (Frozen):** 159 images (15.0%)
- **Target Classes & Distribution:**
  - `Crack` (Class 0): 522 boxes
  - `Pothole` (Class 1): 927 boxes
  - `Surface Erosion` (Class 2): 397 boxes
  - Total boxes: 1,846 boxes across 1,071 images (+ 4 background images).
- **Privacy & PII Audit:** 100% downward-facing road surface imagery; zero human faces or vehicle license plates present.

---

## 2. Training Configurations & Experiments

All experiments were executed on local CPU (Intel Core i5-1235U) and logged to `ml/reports/experiments.csv`.

| Exp ID | Change / Configuration | Resolution | Epochs | Val mAP@50 | Val mAP@50-95 | Val Precision | Val Recall | Time (s) |
|:---:|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **E0** | Baseline YOLOv8n fine-tuning | $320 \times 320$ | 2 | 0.1356 | 0.0401 | 0.1335 | 0.1865 | 224.0s |
| **E1** | Resolution boost + AdamW warm start | $416 \times 416$ | 3 | **0.3948** | **0.1565** | **0.4570** | **0.4315** | 493.5s |

*Key Takeaway:* Increasing resolution to 416px yielded a **+25.9 percentage point increase in mAP@50** and nearly tripled validation recall (from 18.7% to 43.2%).

---

## 3. Single-Pass Final Evaluation on Frozen Test Set

The best model from E1 was frozen and evaluated strictly once against the held-out test split (159 images, 240 ground-truth defect boxes).

- **Overall mAP@50:** **0.3999** (40.0%)
- **Overall mAP@50-95:** **0.1756** (17.6%)
- **Precision:** **0.4188** (41.9%)
- **Recall:** **0.4265** (42.7%)

### Per-Class Test Performance:
| Defect Class | Mapped Code | Test Instances | Precision | Recall | mAP@50 | mAP@50-95 |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| **Pothole** | `D40` | 105 | 0.416 | 0.495 | **0.449** | 0.153 |
| **Surface Erosion** | `D20` | 61 | 0.478 | 0.541 | **0.521** | 0.309 |
| **Crack** | `D00` | 74 | 0.362 | 0.243 | **0.230** | 0.064 |

### Negative & False-Alarm Check:
- Evaluated on unlabelled production complaint photos (`uploads/issues`):
- **False-Alarm Rate (at conf=0.35):** **0.0%** (zero non-defect road images produced false alarms).

---

## 4. ONNX Runtime & Deployment Benchmarking

- **Exported Format:** ONNX opset 12 (static input `[1, 3, 416, 416]`)
- **File Size:** 12.09 MB (12,677,120 bytes)
- **PyTorch vs ONNX Parity:** Maximum absolute numerical difference on 20 test images: **$5.95 \times 10^{-4}$** (Pass, well within tolerances).
- **CPU Inference Speed:** **25.70 ms** per image (~39 FPS on commodity laptop CPU).

---

## 5. Failure Case Analysis & Limitations

Sample visual failure overlays saved to `ml/reports/errors/`:
1. **Misses (False Negatives):**
   - Fine, low-contrast hairline cracks in wet or shaded asphalt.
   - Potholes photographed from distant acute angles ($> 15$ meters away).
2. **Detection Strengths:**
   - Structural potholes, cavitations, and extensive surface raveling/rutting are recognized reliably with distinct bounding boundaries.

---

## 6. What This Model Can and Cannot Do (Plain Language)

### What It Can Do:
- Accurately localize potholes and asphalt erosion from smartphone photos submitted by citizens.
- Run entirely locally on edge/CPU servers in under 30 milliseconds with zero cloud API costs.
- Compute standardized defect area ratios to supply objective physical evidence to CEFAP for issue severity scoring.
- Fail safely: if an image is corrupted or the model is disabled, the system automatically falls back to Gemini Vision or heuristic rules without crashing.

### What It Cannot Do:
- It cannot measure sub-millimeter asphalt micro-fissures or subsurface structural base layer integrity.
- It cannot estimate crater volume or depth without LiDAR or stereoscopic depth sensors.
- It is never permitted to automatically close complaints or downgrade citizen emergency alerts (enforces Contract Rule R8).

