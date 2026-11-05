"""
SmartCivic — Local Text Classifier Baseline Training
Trains a TF-IDF + Logistic Regression baseline for service routing, issue typing,
and emergency possibility flag detection.

GROUP-AWARE SPLIT (Scenario-Level Generalisation):
Data is split strictly by scenario_group using GroupShuffleSplit so that paraphrases
or transliterations of the same underlying event never straddle train and test sets.

DATA COLUMNS REQUIRED:
- text: complaint description (English, Kannada transliteration, or mixed)
- service: target municipal department (roads, water, electricity, sanitation, etc.)
- issue_type: specific defect/problem
- emergency: boolean (True/False or 1/0)
- label_source: human | gemini | synthetic
- scenario_group: grouping identifier preventing paraphrase leakage
"""
import os
import sys
import json
import hashlib
import argparse
from datetime import datetime
from typing import Dict, Any, Tuple
import pandas as pd
import numpy as np
import joblib

from sklearn.model_selection import GroupShuffleSplit
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, f1_score, recall_score


def compute_sha256(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_dataset(csv_path: str) -> pd.DataFrame:
    """Loads and validates required schema."""
    df = pd.read_csv(csv_path)
    required_cols = {"text", "service", "issue_type", "emergency", "label_source", "scenario_group"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"CSV missing required columns: {missing}")

    df = df.dropna(subset=["text", "service", "scenario_group"])
    df["emergency"] = df["emergency"].astype(str).str.lower().isin(["true", "1", "yes"])
    return df


def train_baseline(
    csv_path: str,
    output_model_path: str = "models_artifacts/text_classifier_v1.joblib",
    test_size: float = 0.25,
    random_state: int = 42
) -> Dict[str, Any]:
    """
    Trains TF-IDF vectorizer and group-split Logistic Regression models.
    """
    df = load_dataset(csv_path)
    print(f"[Dataset] Loaded {len(df)} samples across {df['scenario_group'].nunique()} scenario groups.")

    # GroupShuffleSplit ensures paraphrases of the same incident stay in train OR test
    splitter = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=random_state)
    train_idx, test_idx = next(splitter.split(df, groups=df["scenario_group"]))

    train_df = df.iloc[train_idx]
    test_df = df.iloc[test_idx]

    print(f"[Split] Train samples: {len(train_df)} ({train_df['scenario_group'].nunique()} groups)")
    print(f"[Split] Test samples:  {len(test_df)} ({test_df['scenario_group'].nunique()} groups)")

    # TF-IDF with character and word n-grams for Kannada/Indic transliteration resilience
    vectorizer = TfidfVectorizer(
        ngram_range=(2, 5),
        analyzer="char_wb",
        min_df=1,
        sublinear_tf=True
    )

    X_train = vectorizer.fit_transform(train_df["text"])
    X_test = vectorizer.transform(test_df["text"])

    # 1. Service Model
    service_clf = LogisticRegression(class_weight="balanced", max_iter=1000, random_state=random_state)
    service_clf.fit(X_train, train_df["service"])

    # 2. Issue Type Model
    type_clf = LogisticRegression(class_weight="balanced", max_iter=1000, random_state=random_state)
    type_clf.fit(X_train, train_df["issue_type"])

    # 3. Emergency Flag Model (High class weight for public safety)
    emerg_clf = LogisticRegression(class_weight={False: 1.0, True: 3.0}, max_iter=1000, random_state=random_state)
    emerg_clf.fit(X_train, train_df["emergency"])

    # Evaluation on held-out scenario groups
    y_service_pred = service_clf.predict(X_test)
    y_emerg_pred = emerg_clf.predict(X_test)

    macro_f1 = float(f1_score(test_df["service"], y_service_pred, average="macro", zero_division=0))
    emerg_recall = float(recall_score(test_df["emergency"], y_emerg_pred, zero_division=0))

    print("\n--- Test Evaluation (Scenario Group Split) ---")
    print(f"Service Macro F1: {macro_f1:.4f}")
    print(f"Emergency Recall: {emerg_recall:.4f}")

    # Build model artifact package
    bundle = {
        "vectorizer": vectorizer,
        "service_model": service_clf,
        "issue_type_model": type_clf,
        "emergency_model": emerg_clf,
        "classes": {
            "service": list(service_clf.classes_),
            "issue_type": list(type_clf.classes_)
        },
        "version": "1.0.0",
        "trained_at": datetime.utcnow().isoformat()
    }

    os.makedirs(os.path.dirname(output_model_path), exist_ok=True)
    joblib.dump(bundle, output_model_path, compress=3)
    sha256_hash = compute_sha256(output_model_path)

    # Manifest metadata
    manifest = {
        "model_file": os.path.basename(output_model_path),
        "sha256": sha256_hash,
        "model_type": "tfidf_logreg_baseline",
        "classes": list(service_clf.classes_),
        "version": "1.0.0",
        "trained_at": bundle["trained_at"],
        "metrics": {
            "service_macro_f1": round(macro_f1, 4),
            "emergency_recall": round(emerg_recall, 4)
        }
    }
    manifest_path = os.path.join(os.path.dirname(output_model_path), "text_classifier_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"[Success] Saved model bundle: {output_model_path}")
    print(f"[Success] Checksum SHA256:    {sha256_hash}")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train SmartCivic Local Text Baseline")
    parser.add_argument("--data", default="ml/datasets/text_classification_template.csv", help="Path to labelled CSV")
    parser.add_argument("--out", default="models_artifacts/text_classifier_v1.joblib", help="Output model bundle path")
    args = parser.parse_args()

    if os.path.exists(args.data):
        train_baseline(args.data, args.out)
    else:
        print(f"Data file '{args.data}' not found.")

