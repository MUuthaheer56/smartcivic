"""
SmartCivic — Stage D: Baseline E0 Experiment & Validation Failure Analysis
Runs YOLOv8n baseline fine-tuning on CPU:
- Evaluates purely on validation set (Test set remains strictly frozen).
- Logs metrics to ml/reports/experiments.csv.
- Extracts false positives and misses on validation images for STOP 3 review.
- Generates a turnkey Google Colab notebook for free T4 GPU extended training.
"""
import os
import sys
import time
import csv
import hashlib
import json
from typing import Dict, Any, List

import cv2
import numpy as np
from PIL import Image

WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
WORK_DATASET_DIR = os.path.join(WORKSPACE_ROOT, "ml", "datasets", "work")
DATA_YAML_PATH = os.path.join(WORK_DATASET_DIR, "data.yaml")
EXPERIMENTS_CSV_PATH = os.path.join(WORKSPACE_ROOT, "ml", "reports", "experiments.csv")
COLAB_NOTEBOOK_PATH = os.path.join(WORKSPACE_ROOT, "ml", "training", "SmartCivic_RoadDamage_YOLOv8_Colab.ipynb")
VALIDATION_FAILURES_DIR = os.path.join(WORKSPACE_ROOT, "ml", "reports", "audit", "validation_failures")

os.makedirs(VALIDATION_FAILURES_DIR, exist_ok=True)
os.makedirs(os.path.join(WORKSPACE_ROOT, "ml", "reports"), exist_ok=True)

CLASS_NAMES = ["Crack", "Pothole", "Surface Erosion"]

def generate_colab_notebook():
    """Generates a complete, turnkey Colab notebook for free T4 GPU training."""
    notebook_content = {
        "nbformat": 4,
        "nbformat_minor": 0,
        "metadata": {
            "accelerator": "GPU",
            "colab": {"provenance": []},
            "language_info": {"name": "python"}
        },
        "cells": [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "# SmartCivic — Road Damage YOLOv8 Detection Training (GPU)\n",
                    "This notebook trains the YOLOv8 model for road defect detection (`Crack`, `Pothole`, `Surface Erosion`) on a free GPU (T4/V100).\n",
                    "- Follows the SmartCivic Master Implementation Plan.\n",
                    "- Saves checkpoints and exported ONNX models directly to Google Drive."
                ]
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "# 1. Verify GPU availability and install Ultralytics\n",
                    "!nvidia-smi\n",
                    "!pip install -q ultralytics onnx onnxruntime"
                ]
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "# 2. Optional: Mount Google Drive to preserve checkpoints\n",
                    "from google.colab import drive\n",
                    "drive.mount('/content/drive')\n",
                    "import os\n",
                    "DRIVE_DIR = '/content/drive/MyDrive/SmartCivic_Models'\n",
                    "os.makedirs(DRIVE_DIR, exist_ok=True)\n",
                    "print('Checkpoints will be saved to:', DRIVE_DIR)"
                ]
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "# 3. Upload and extract datasets (or download workspace dataset zip)\n",
                    "# If using the zipped 'work' dataset from your local machine:\n",
                    "# from google.colab import files\n",
                    "# files.upload() # upload smartcivic_dataset_work.zip\n",
                    "!mkdir -p /content/dataset\n",
                    "# !unzip -q smartcivic_dataset_work.zip -d /content/dataset/"
                ]
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "# 4. Define data.yaml\n",
                    "data_yaml = '''\n",
                    "path: /content/dataset\n",
                    "train: train/images\n",
                    "val: val/images\n",
                    "test: test/images\n",
                    "nc: 3\n",
                    "names: ['Crack', 'Pothole', 'Surface Erosion']\n",
                    "'''\n",
                    "with open('/content/data.yaml', 'w') as f:\n",
                    "    f.write(data_yaml)"
                ]
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "# 5. Full GPU Fine-Tuning (50 epochs, imgsz=640, early stopping patience=10)\n",
                    "from ultralytics import YOLO\n",
                    "model = YOLO('yolov8n.pt')\n",
                    "results = model.train(\n",
                    "    data='/content/data.yaml',\n",
                    "    epochs=50,\n",
                    "    imgsz=640,\n",
                    "    batch=16,\n",
                    "    patience=10,\n",
                    "    seed=42,\n",
                    "    device=0,\n",
                    "    project='/content/runs',\n",
                    "    name='smartcivic_yolov8n'\n",
                    ")"
                ]
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "# 6. Export best model to ONNX with dynamic=False (CPU friendly)\n",
                    "best_model_path = '/content/runs/smartcivic_yolov8n/weights/best.pt'\n",
                    "best_model = YOLO(best_model_path)\n",
                    "onnx_file = best_model.export(format='onnx', imgsz=640, opset=12, dynamic=False)\n",
                    "print('Exported ONNX file:', onnx_file)\n",
                    "!cp {onnx_file} /content/drive/MyDrive/SmartCivic_Models/model.onnx\n",
                    "!cp {best_model_path} /content/drive/MyDrive/SmartCivic_Models/best.pt\n",
                    "print('Saved model to Google Drive!')"
                ]
            }
        ]
    }
    with open(COLAB_NOTEBOOK_PATH, "w", encoding="utf-8") as f:
        json.dump(notebook_content, f, indent=2)
    print(f"[Train] Turnkey Google Colab notebook created at: {COLAB_NOTEBOOK_PATH}")

def run_baseline_e0():
    print("[Train] Checking environment and ultralytics import...")
    from ultralytics import YOLO

    generate_colab_notebook()

    print("[Train] Starting Baseline E0 smoke fine-tuning run on local CPU...")
    start_time = time.time()

    # Pretrained YOLOv8n
    model = YOLO("yolov8n.pt")

    # Run fine-tuning for 2 epochs on CPU (small imgsz=320, batch=16) to validate training dynamics
    # and compute exact baseline validation metrics without timing out
    train_results = model.train(
        data=DATA_YAML_PATH,
        epochs=2,
        imgsz=320,
        batch=16,
        device="cpu",
        seed=42,
        project=os.path.join(WORKSPACE_ROOT, "ml", "training", "runs"),
        name="experiment_E0",
        exist_ok=True,
        verbose=True
    )

    training_duration = time.time() - start_time
    print(f"[Train] Baseline E0 training completed in {training_duration:.1f}s.")

    # Validation on Val split (Val images: 159, Test split remains frozen)
    print("[Train] Running evaluation on VALIDATION split (test set remains frozen)...")
    val_results = model.val(data=DATA_YAML_PATH, split="val", imgsz=320, device="cpu")

    # Extract metrics safely
    metrics_dict = val_results.results_dict
    map50 = float(metrics_dict.get("metrics/mAP50(B)", 0.0))
    map50_95 = float(metrics_dict.get("metrics/mAP50-95(B)", 0.0))
    precision = float(metrics_dict.get("metrics/precision(B)", 0.0))
    recall = float(metrics_dict.get("metrics/recall(B)", 0.0))

    # Per-class metrics
    class_names = CLASS_NAMES
    per_class_res = {}
    try:
        class_map50 = val_results.box.maps
        for idx, cname in enumerate(class_names):
            if idx < len(class_map50):
                per_class_res[cname] = float(class_map50[idx])
    except Exception:
        pass

    print(f"[Train] Validation Results — mAP50: {map50:.4f}, mAP50-95: {map50_95:.4f}, Precision: {precision:.4f}, Recall: {recall:.4f}")
    print(f"[Train] Per-class mAP50-95: {per_class_res}")

    # Log to experiments.csv
    exp_fields = [
        "id", "change", "config_hash", "seed", "epochs", "imgsz", "device",
        "val_mAP50", "val_mAP50_95", "val_precision", "val_recall", "per_class_mAP", "training_time_s"
    ]
    file_exists = os.path.exists(EXPERIMENTS_CSV_PATH)
    config_str = f"yolov8n_epochs2_imgsz320_batch16_seed42"
    cfg_hash = hashlib.sha256(config_str.encode()).hexdigest()[:8]

    with open(EXPERIMENTS_CSV_PATH, "a" if file_exists else "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=exp_fields)
        if not file_exists:
            writer.writeheader()
        writer.writerow({
            "id": "E0",
            "change": "Baseline fine-tuning (YOLOv8n, 2 ep, imgsz 320, CPU)",
            "config_hash": cfg_hash,
            "seed": 42,
            "epochs": 2,
            "imgsz": 320,
            "device": "cpu",
            "val_mAP50": round(map50, 4),
            "val_mAP50_95": round(map50_95, 4),
            "val_precision": round(precision, 4),
            "val_recall": round(recall, 4),
            "per_class_mAP": json.dumps(per_class_res),
            "training_time_s": round(training_duration, 1)
        })
    print(f"[Train] Experiment record appended to {EXPERIMENTS_CSV_PATH}")

    # Inspect failure cases on validation images (misses & false alarms)
    val_img_dir = os.path.join(WORK_DATASET_DIR, "val", "images")
    val_lbl_dir = os.path.join(WORK_DATASET_DIR, "val", "labels")

    val_images = [os.path.join(val_img_dir, f) for f in os.listdir(val_img_dir) if f.endswith((".jpg", ".png"))]
    sample_val = val_images[:30]

    failure_cases = []
    for img_p in sample_val:
        fname = os.path.basename(img_p)
        base_name = os.path.splitext(fname)[0]
        lbl_p = os.path.join(val_lbl_dir, base_name + ".txt")

        # Ground truth count
        gt_boxes = 0
        if os.path.exists(lbl_p):
            with open(lbl_p) as f:
                gt_boxes = len([l for l in f if l.strip()])

        # Predict
        preds = model.predict(img_p, imgsz=320, conf=0.25, verbose=False)[0]
        det_boxes = len(preds.boxes)

        if gt_boxes > 0 and det_boxes == 0:
            failure_cases.append({
                "type": "miss (false negative)",
                "file": fname,
                "ground_truth_count": gt_boxes,
                "detected_count": det_boxes,
                "cause": "Under-detected defect at low epochs / low resolution"
            })
        elif gt_boxes == 0 and det_boxes > 0:
            failure_cases.append({
                "type": "false alarm (false positive)",
                "file": fname,
                "ground_truth_count": gt_boxes,
                "detected_count": det_boxes,
                "cause": "Background artifact flagged as road defect"
            })

    print(f"[Train] Identified {len(failure_cases)} validation failure cases for STOP 3 review.")

    # Save validation failure summary
    val_failure_report = {
        "experiment": "E0",
        "validation_metrics": {
            "mAP50": map50,
            "mAP50_95": map50_95,
            "precision": precision,
            "recall": recall,
            "per_class_mAP": per_class_res
        },
        "training_time_seconds": training_duration,
        "sample_failure_cases": failure_cases[:10]
    }
    with open(os.path.join(VALIDATION_FAILURES_DIR, "e0_validation_failures.json"), "w", encoding="utf-8") as f:
        json.dump(val_failure_report, f, indent=2)

    return val_failure_report

if __name__ == "__main__":
    run_baseline_e0()

