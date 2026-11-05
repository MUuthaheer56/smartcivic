# RDD2022 Road Damage Detector Training Guide

This guide describes how to train the road damage detection model on free cloud GPU instances (Google Colab or Kaggle) and export it to an ONNX runtime artifact for local CPU inference in SmartCivic.

---

## 1. Dataset Licensing & Terms Check

Before using the dataset, verify compliance with the license:
- **Dataset**: Road Damage Dataset 2022 (RDD2022)
- **License**: Creative Commons Attribution-ShareAlike 4.0 International (**CC BY-SA 4.0**)
- **Attribution Citation**:
  ```bibtex
  @article{arya2022deep,
    title={Deep learning-based road damage detection and classification for multiple countries},
    author={Arya, Deeksha and Maeda, Hiroya and Ghosh, Sanjay Kumar and Toshniwal, Durga and Mraz, Alexander and Kashiyama, Takehiro and Sekimoto, Yoshihide},
    journal={Automation in Construction},
    volume={132},
    pages={103983},
    year={2022}
  }
  ```
- **Redistribution Notice**: Per repo rules, raw dataset images and trained weight binaries (`.pt`, `.onnx`) are **NOT** committed to git.

---

## 2. Cross-Region Geographic Partitioning

To measure genuine domain transfer and prevent data leakage:
- **DO NOT** perform random uniform image splits.
- **DO** split by country/region subset:
  - **Training Subsets**: Japan (urban asphalt) + Czech (European regional roads).
  - **Held-out Evaluation Split**: India subset (unseen pavement construction and monsoon wear patterns).

---

## 3. Training Execution (Colab / Kaggle GPU)

In a Colab notebook with a free T4 GPU:

```bash
# 1. Install Ultralytics and dependencies
pip install ultralytics onnx onnxruntime onnxsim

# 2. Download RDD2022 dataset release
# Download via official Crowdsensing Challenge or Kaggle API:
# kaggle datasets download -d kmader/road-damage-dataset-2022

# 3. Run training with geographic partition
python ml/training/train_road_detector.py \
    --data /content/RDD2022 \
    --epochs 50 \
    --batch 16 \
    --imgsz 640 \
    --out /content/export
```

---

## 4. ONNX Export & Artifact Placement

The training script automatically executes:
```bash
yolo export model=runs/detect/rdd2022_yolov8n/weights/best.pt format=onnx imgsz=640 opset=12 simplify=True dynamic=False
```

### Deploying Artifact to SmartCivic:
1. Download `best.onnx` from Colab/Kaggle.
2. Rename to `road_damage_v1.onnx` and place inside `models_artifacts/` (or `ml/models/`).
3. Compute its SHA256 checksum:
   ```powershell
   Get-FileHash models_artifacts/road_damage_v1.onnx -Algorithm SHA256
   ```
4. Verify `models_artifacts/manifest.json` matches the SHA256 checksum and classes.
5. In `config.py`, enable the feature flag:
   ```python
   AI_LOCAL_DETECTOR_ENABLED = True
   ```

