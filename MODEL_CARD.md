# SmartCivic Model Card: Road Damage Defect Detector v1

## Model Details
- **Model Name:** SmartCivic Road Damage Detector (`road_damage_v1.onnx`)
- **Version:** v1.0
- **Architecture:** YOLOv8n (nano variant, CPU-quantized ONNX export)
- **Input Dimensions:** `[1, 3, 416, 416]` (RGB float32 normalized 0.0–1.0)
- **Output Shape:** `[1, 7, 3549]` (4 bounding box coordinates + 3 class confidence scores)
- **Model Size:** 12.68 MB (12,678,126 bytes)
- **SHA-256 Checksum:** `07d9464095daad753d2b66f02e11a08a8b13537b77920f7692603bdefef11b08`
- **Execution Provider:** ONNX Runtime (`CPUExecutionProvider`)

## Classes and Label Mapping
The model was fine-tuned on road surface anomalies categorized into 3 defect classes:
1. **Crack (`D00`)**: Longitudinal and transverse road cracks.
2. **Pothole (`D40`)**: Road surface potholes and deep cavity depressions.
3. **Surface Erosion (`D20`)**: Alligator cracking, raveling, and severe asphalt wear.

## Training & Dataset
- **Base Architecture:** Ultralytics YOLOv8n pre-trained on COCO.
- **Source Dataset:** Road Damage Dataset (RDD2022 subset / Roboflow export).
- **Training Epochs:** 50 epochs on single GPU, exported to ONNX for CPU inference.
- **License of Training Data:** CC BY 4.0.

## Performance Metrics (Held-Out Test Set)
Evaluated across 159 held-out test images (`ml/datasets/work/test/images/`):
- **Overall mAP@50:** `0.3999`
- **Overall mAP@50-95:** `0.1756`
- **Overall Precision:** `0.4188`
- **Overall Recall:** `0.4265`
- **Per-Class Breakdown:**
  - `Pothole (D40)`: Precision 0.416, Recall 0.495, mAP@50 0.449
  - `Surface Erosion (D20)`: Precision 0.478, Recall 0.541, mAP@50 0.520
  - `Crack (D00)`: Precision 0.362, Recall 0.243, mAP@50 0.230
- **CPU Inference Latency (Intel/AMD x86_64 CPU):**
  - Mean: `15.91 ms`
  - 95th Percentile: `17.92 ms`

## Intended Use & Safety Controls
- **Intended Purpose:** Rapid, local, privacy-preserving visual detection of road defects in civic complaints without external cloud transmission.
- **Out of Scope:** Structural engineering assessments, autonomous vehicle navigation, or high-speed traffic enforcement.
- **Safety Interlocks:** Predictions are fused through CEFAP with text analysis and corroborative community evidence. Visual detections alone never trigger automatic dispatch without officer verification.

