"""
SmartCivic — Stage D: Experiment E1
Second budgeted experiment:
- Uses higher resolution (imgsz=416 vs 320) and augmented learning dynamics.
- Evaluates on validation set only (test set remains frozen).
- Appends results to ml/reports/experiments.csv.
"""
import os
import sys
import time
import csv
import hashlib
import json
from ultralytics import YOLO

WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
WORK_DATASET_DIR = os.path.join(WORKSPACE_ROOT, "ml", "datasets", "work")
DATA_YAML_PATH = os.path.join(WORK_DATASET_DIR, "data.yaml")
EXPERIMENTS_CSV_PATH = os.path.join(WORKSPACE_ROOT, "ml", "reports", "experiments.csv")
E0_BEST_WEIGHTS = os.path.join(WORKSPACE_ROOT, "ml", "training", "runs", "experiment_E0", "weights", "best.pt")

CLASS_NAMES = ["Crack", "Pothole", "Surface Erosion"]

def run_experiment_e1():
    print("[Experiment E1] Starting Experiment E1...")
    start_time = time.time()

    init_weights = E0_BEST_WEIGHTS if os.path.exists(E0_BEST_WEIGHTS) else "yolov8n.pt"
    print(f"[Experiment E1] Initializing model from: {init_weights}")
    model = YOLO(init_weights)

    # Train for 3 epochs at imgsz=416 with light mosaic and flip
    train_res = model.train(
        data=DATA_YAML_PATH,
        epochs=3,
        imgsz=416,
        batch=16,
        device="cpu",
        seed=42,
        lr0=0.005,
        project=os.path.join(WORKSPACE_ROOT, "ml", "training", "runs"),
        name="experiment_E1",
        exist_ok=True,
        verbose=True
    )

    training_duration = time.time() - start_time
    print(f"[Experiment E1] Training completed in {training_duration:.1f}s.")

    # Validate on validation set only
    print("[Experiment E1] Evaluating on validation set...")
    val_results = model.val(data=DATA_YAML_PATH, split="val", imgsz=416, device="cpu")

    metrics_dict = val_results.results_dict
    map50 = float(metrics_dict.get("metrics/mAP50(B)", 0.0))
    map50_95 = float(metrics_dict.get("metrics/mAP50-95(B)", 0.0))
    precision = float(metrics_dict.get("metrics/precision(B)", 0.0))
    recall = float(metrics_dict.get("metrics/recall(B)", 0.0))

    per_class_res = {}
    try:
        class_map50 = val_results.box.maps
        for idx, cname in enumerate(CLASS_NAMES):
            if idx < len(class_map50):
                per_class_res[cname] = float(class_map50[idx])
    except Exception:
        pass

    print(f"[Experiment E1] Results — mAP50: {map50:.4f}, mAP50-95: {map50_95:.4f}, Precision: {precision:.4f}, Recall: {recall:.4f}")
    print(f"[Experiment E1] Per-class mAP50-95: {per_class_res}")

    # Append to experiments.csv
    exp_fields = [
        "id", "change", "config_hash", "seed", "epochs", "imgsz", "device",
        "val_mAP50", "val_mAP50_95", "val_precision", "val_recall", "per_class_mAP", "training_time_s"
    ]
    cfg_str = "yolov8n_epochs3_imgsz416_batch16_seed42"
    cfg_hash = hashlib.sha256(cfg_str.encode()).hexdigest()[:8]

    with open(EXPERIMENTS_CSV_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=exp_fields)
        writer.writerow({
            "id": "E1",
            "change": "Resolution boost (imgsz 416, 3 ep, fine-tuned from E0 best, CPU)",
            "config_hash": cfg_hash,
            "seed": 42,
            "epochs": 3,
            "imgsz": 416,
            "device": "cpu",
            "val_mAP50": round(map50, 4),
            "val_mAP50_95": round(map50_95, 4),
            "val_precision": round(precision, 4),
            "val_recall": round(recall, 4),
            "per_class_mAP": json.dumps(per_class_res),
            "training_time_s": round(training_duration, 1)
        })

    print(f"[Experiment E1] Logged to {EXPERIMENTS_CSV_PATH}.")
    return val_results

if __name__ == "__main__":
    run_experiment_e1()

