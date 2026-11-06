"""
scripts/eval_real_photos.py - Evaluates Shipped Road Damage Detector on Real Bengaluru Photos
Reads: data/real_photos/labels.csv (columns: filename, has_defect, defect_type)
Computes:
- Per-photo hit, miss, and false alarm
- Confusion counts across classes
- Failures by filename (false negatives and false positives)
Guard: Runs ONLY if data/real_photos/ directory exists.
"""
import os
import sys
import csv
import json
import argparse
import numpy as np

WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.path.join(WORKSPACE_ROOT, "data", "real_photos")
LABELS_CSV = os.path.join(DATA_DIR, "labels.csv")
MODEL_PATH = os.path.join(WORKSPACE_ROOT, "ml", "models", "road_damage_v1.onnx")


def evaluate_real_photos():
    if not os.path.exists(DATA_DIR):
        print(f"[STATUS: BLOCKED / NOT RUN] Directory '{DATA_DIR}' does not exist.")
        return None

    if not os.path.exists(LABELS_CSV):
        print(f"[STATUS: BLOCKED / NOT RUN] Labels file '{LABELS_CSV}' does not exist.")
        return None

    from services.ai.road_detector import detect_road_damage

    rows = []
    with open(LABELS_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)

    print(f"[*] Found {len(rows)} real photo annotations in '{LABELS_CSV}'. Evaluating...")

    hits = 0
    misses = 0
    false_alarms = 0
    correct_negatives = 0

    confusion = {}
    failures = []

    for r in rows:
        fname = r["filename"]
        has_defect_gt = str(r["has_defect"]).strip().lower() in ("true", "1", "yes")
        defect_type_gt = (r.get("defect_type") or "none").strip().lower()

        img_path = os.path.join(DATA_DIR, fname)
        if not os.path.exists(img_path):
            print(f"[WARNING] Image '{fname}' missing from '{DATA_DIR}', skipping.")
            continue

        pred = detect_road_damage(img_path)
        val = pred.get("value", {})
        detections = val.get("detections", [])
        has_defect_pred = len(detections) > 0
        primary_defect_pred = (val.get("primary_defect") or "none").strip().lower()

        pair = (defect_type_gt, primary_defect_pred)
        confusion[pair] = confusion.get(pair, 0) + 1

        if has_defect_gt and has_defect_pred:
            hits += 1
        elif has_defect_gt and not has_defect_pred:
            misses += 1
            failures.append({
                "filename": fname,
                "type": "FALSE_NEGATIVE_MISS",
                "ground_truth": defect_type_gt,
                "prediction": primary_defect_pred
            })
        elif not has_defect_gt and has_defect_pred:
            false_alarms += 1
            failures.append({
                "filename": fname,
                "type": "FALSE_POSITIVE_ALARM",
                "ground_truth": defect_type_gt,
                "prediction": primary_defect_pred
            })
        else:
            correct_negatives += 1

    total = hits + misses + false_alarms + correct_negatives
    out = {
        "dataset_path": DATA_DIR,
        "total_evaluated": total,
        "hits": hits,
        "misses": misses,
        "false_alarms": false_alarms,
        "correct_negatives": correct_negatives,
        "precision": round(hits / max(hits + false_alarms, 1), 4),
        "recall": round(hits / max(hits + misses, 1), 4),
        "confusion_pairs": {f"{k[0]} -> {k[1]}": v for k, v in confusion.items()},
        "failures": failures
    }

    out_file = os.path.join(WORKSPACE_ROOT, "results", "real_photos_eval.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)

    print(f"[SUCCESS] Real photos evaluation complete. Hits: {hits}, Misses: {misses}, False Alarms: {false_alarms}")
    print(f"Results saved to '{out_file}'.")
    return out


if __name__ == "__main__":
    evaluate_real_photos()

