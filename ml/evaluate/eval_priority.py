"""
SmartCivic — ML Prioritisation Model & Baseline Evaluation
Evaluates ML Prioritiser (XGBoost) against CEFAP and Ablation Baselines M1-M4
on the held-out test split. Computes Tree SHAP values for interpretability.
Writes committed report to ml/reports/priority_model_evaluation.json.
"""
import os
import sys
import json
import joblib
import pandas as pd
import numpy as np
import shap
from sklearn.model_selection import GroupShuffleSplit
from sklearn.metrics import f1_score, precision_score, recall_score, confusion_matrix

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT_DIR)

from services.cefap_pipeline import (
    baseline_m1,
    baseline_m2,
    baseline_m3,
    _priority,
    DEFAULT_WEIGHTS
)

DATASET_PATH = os.path.join(ROOT_DIR, "ml", "datasets", "priority_training_dataset.csv")
MODEL_PATH = os.path.join(ROOT_DIR, "models_artifacts", "priority_model_v1.joblib")
REPORT_PATH = os.path.join(ROOT_DIR, "ml", "reports", "priority_model_evaluation.json")

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
PRIORITY_CLASSES = ["P0", "P1", "P2", "P3"]


def evaluate_baselines_and_ml():
    if not os.path.exists(DATASET_PATH):
        raise FileNotFoundError(f"Dataset missing at {DATASET_PATH}")
    if not os.path.exists(MODEL_PATH):
        raise FileNotFoundError(f"Model bundle missing at {MODEL_PATH}")

    df = pd.read_csv(DATASET_PATH)
    bundle = joblib.load(MODEL_PATH)
    model = bundle["model"]

    # Recreate the exact same GroupShuffleSplit
    X = df[FEATURE_COLS].copy()
    X["monsoon_active"] = X["monsoon_active"].astype(int)
    y = df["ground_truth_priority"]
    groups = df["ward_id"]

    gss = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=42)
    _, test_idx = next(gss.split(X, y, groups=groups))

    test_df = df.iloc[test_idx].copy()
    X_test = X.iloc[test_idx]
    y_true = y.iloc[test_idx]

    # 1. ML Model Predictions
    y_pred_code = model.predict(X_test)
    y_pred_ml = [INV_LABEL_MAP[c] for c in y_pred_code]

    # 2. Baseline M1 (Text Severity Only)
    y_pred_m1 = [baseline_m1(row["text_severity"])["priority"] for _, row in test_df.iterrows()]

    # 3. Baseline M2 (Text + Image Average)
    y_pred_m2 = [baseline_m2(row["text_severity"], row["image_severity"])["priority"] for _, row in test_df.iterrows()]

    # 4. Baseline M3 (Text + Image + Location)
    y_pred_m3 = [baseline_m3(row["text_severity"], row["image_severity"], row["location_impact"])["priority"] for _, row in test_df.iterrows()]

    # 5. Baseline M4 (All 6 signals, no reliability E)
    y_pred_m4 = []
    w = DEFAULT_WEIGHTS
    for _, row in test_df.iterrows():
        ws = (w["wS"]*row["text_severity"] + w["wI"]*row["image_severity"] +
              w["wL"]*row["location_impact"] + w["wC"]*row["corroboration"] +
              w["wR"]*row["recurrence"] + w["wT"]*min(row["sla_risk"], 1.0))
        y_pred_m4.append(_priority(round(min(ws, 1.0), 3), False))

    # 6. Rule-based CEFAP (Adaptive weights + reliability E + Monsoon)
    y_pred_cefap = test_df["cefap_priority"].tolist()

    # Evaluation helper
    def calc_metrics(preds):
        macro_f1 = f1_score(y_true, preds, average="macro", zero_division=0)
        macro_prec = precision_score(y_true, preds, average="macro", zero_division=0)
        macro_rec = recall_score(y_true, preds, average="macro", zero_division=0)

        # Critical (P0 / P1) recall
        crit_true = y_true.isin(["P0", "P1"])
        crit_pred = [p in ["P0", "P1"] for p in preds]
        crit_rec = float(sum(1 for t, p in zip(crit_true, crit_pred) if t and p) / crit_true.sum()) if crit_true.sum() > 0 else 0.0

        return {
            "macro_f1": round(float(macro_f1), 4),
            "macro_precision": round(float(macro_prec), 4),
            "macro_recall": round(float(macro_rec), 4),
            "critical_recall": round(float(crit_rec), 4)
        }

    comparison = {
        "ML_Priority_RandomForest": calc_metrics(y_pred_ml),
        "CEFAP_Adaptive_Fusion": calc_metrics(y_pred_cefap),
        "M4_No_Reliability": calc_metrics(y_pred_m4),
        "M3_Location_Added": calc_metrics(y_pred_m3),
        "M2_Text_Image_Only": calc_metrics(y_pred_m2),
        "M1_Text_Only": calc_metrics(y_pred_m1)
    }

    # Confusion Matrix for ML Model
    cm = confusion_matrix(y_true, y_pred_ml, labels=PRIORITY_CLASSES)

    # 7. SHAP Feature Attribution
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X_test)

    # If multi-class, shap_values is a list of arrays or 3D array
    if isinstance(shap_values, list):
        mean_abs_shap = np.mean([np.abs(sv).mean(axis=0) for sv in shap_values], axis=0)
    elif len(shap_values.shape) == 3:
        mean_abs_shap = np.abs(shap_values).mean(axis=(0, 2))
    else:
        mean_abs_shap = np.abs(shap_values).mean(axis=0)

    shap_ranking = [
        {"feature": feat, "mean_abs_shap": round(float(score), 4)}
        for feat, score in sorted(zip(FEATURE_COLS, mean_abs_shap), key=lambda x: x[1], reverse=True)
    ]

    report = {
        "evaluation_name": "ML Prioritisation Model & Ablation Comparison",
        "evaluated_at": pd.Timestamp.utcnow().isoformat(),
        "model_artifact": "models_artifacts/priority_model_v1.joblib",
        "test_dataset": "ml/datasets/priority_training_dataset.csv",
        "total_test_samples": len(test_df),
        "test_wards_held_out": int(test_df["ward_id"].nunique()),
        "synthetic": bool(test_df["synthetic"].any()),
        "label_source_breakdown": test_df["label_source"].value_counts().to_dict(),
        "models_comparison": comparison,
        "ml_confusion_matrix": {
            "labels": PRIORITY_CLASSES,
            "matrix": cm.tolist()
        },
        "shap_feature_importance": shap_ranking
    }

    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print("\n================ ML Prioritisation Evaluation ================")
    print(f"Test Samples: {len(test_df)} across {test_df['ward_id'].nunique()} held-out wards")
    print(f"Label Sources: {test_df['label_source'].value_counts().to_dict()}")
    print("\n--- Models Comparison ---")
    for name, mets in comparison.items():
        print(f"  {name:25s} | Macro F1: {mets['macro_f1']:.4f} | Critical Recall: {mets['critical_recall']:.4f}")
    print("\n--- Top SHAP Features ---")
    for item in shap_ranking[:5]:
        print(f"  {item['feature']:22s} | mean |SHAP|: {item['mean_abs_shap']:.4f}")
    print(f"\n[Report Committed] Saved to {REPORT_PATH}")
    return report


if __name__ == "__main__":
    evaluate_baselines_and_ml()
