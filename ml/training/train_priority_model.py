"""
SmartCivic — ML Prioritisation Model Training
Trains a gradient-boosted tree / Random Forest priority classifier on CEFAP signals.
Uses GroupShuffleSplit on ward_id to prevent geographic data leakage.
Exports model bundle and manifest to models_artifacts/.
"""
import os
import sys
import json
import hashlib
import joblib
import pandas as pd
import numpy as np
from sklearn.model_selection import GroupShuffleSplit
from sklearn.metrics import classification_report, f1_score
from xgboost import XGBClassifier
from sklearn.ensemble import RandomForestClassifier

# Paths
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DATASET_PATH = os.path.join(ROOT_DIR, "ml", "datasets", "priority_training_dataset.csv")
ARTIFACT_DIR = os.path.join(ROOT_DIR, "models_artifacts")
MODEL_OUT = os.path.join(ARTIFACT_DIR, "priority_model_v1.joblib")
MANIFEST_OUT = os.path.join(ARTIFACT_DIR, "priority_model_manifest.json")

FEATURE_COLS = [
    "text_severity",
    "image_severity",
    "location_impact",
    "corroboration",
    "recurrence",
    "sla_risk",
    "evidence_reliability",
    "disagreement",
    "monsoon_active"
]

LABEL_MAP = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
INV_LABEL_MAP = {0: "P0", 1: "P1", 2: "P2", 3: "P3"}


def compute_sha256(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def train_priority_model():
    if not os.path.exists(DATASET_PATH):
        raise FileNotFoundError(f"Priority dataset not found at {DATASET_PATH}. Run build_priority_dataset.py first.")

    df = pd.read_csv(DATASET_PATH)
    print(f"[Dataset] Loaded {len(df)} samples across {df['ward_id'].nunique()} wards.")
    print(f"[Label Sources] {df['label_source'].value_counts().to_dict()}")

    # Prepare features and labels
    X = df[FEATURE_COLS].copy()
    X["monsoon_active"] = X["monsoon_active"].astype(int)
    y = df["ground_truth_priority"].map(LABEL_MAP)
    groups = df["ward_id"]

    # GroupShuffleSplit on ward_id (test on entirely unseen wards)
    gss = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=42)
    train_idx, test_idx = next(gss.split(X, y, groups=groups))

    X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
    y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]

    print(f"[Split] Train samples: {len(X_train)} ({groups.iloc[train_idx].nunique()} wards)")
    print(f"[Split] Test samples:  {len(X_test)} ({groups.iloc[test_idx].nunique()} wards)")

    # Train Random Forest classifier with balanced class weighting
    model = RandomForestClassifier(
        n_estimators=120,
        max_depth=6,
        class_weight="balanced",
        random_state=42
    )
    model.fit(X_train, y_train)

    # Evaluate on held-out unseen wards
    y_pred = model.predict(X_test)
    macro_f1 = f1_score(y_test, y_pred, average="macro")

    # Critical recall (P0 + P1)
    crit_mask = y_test.isin([0, 1])
    crit_recall = float((y_pred[crit_mask] == y_test[crit_mask]).mean()) if crit_mask.sum() > 0 else 0.0

    print("\n--- Test Evaluation (Unseen Wards) ---")
    print(f"Macro F1:        {macro_f1:.4f}")
    print(f"Critical Recall: {crit_recall:.4f}")

    # Build model artifact bundle
    os.makedirs(ARTIFACT_DIR, exist_ok=True)
    bundle = {
        "model": model,
        "feature_names": FEATURE_COLS,
        "label_map": LABEL_MAP,
        "inv_label_map": INV_LABEL_MAP,
        "model_type": "random_forest",
        "trained_at": pd.Timestamp.utcnow().isoformat(),
        "train_samples": len(X_train),
        "test_samples": len(X_test)
    }

    joblib.dump(bundle, MODEL_OUT)
    checksum = compute_sha256(MODEL_OUT)

    manifest = {
        "model_name": "priority_model_v1",
        "artifact_file": "priority_model_v1.joblib",
        "sha256": checksum,
        "feature_names": FEATURE_COLS,
        "macro_f1": round(float(macro_f1), 4),
        "critical_recall": round(float(crit_recall), 4),
        "train_sample_count": len(X_train),
        "test_sample_count": len(X_test),
        "synthetic": bool(df["synthetic"].any()),
        "label_sources": df["label_source"].value_counts().to_dict()
    }

    with open(MANIFEST_OUT, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"[Success] Saved model bundle: {MODEL_OUT}")
    print(f"[Success] Manifest written:   {MANIFEST_OUT}")
    print(f"[Success] Checksum SHA256:    {checksum}")
    return bundle, manifest


if __name__ == "__main__":
    train_priority_model()
