"""
SmartCivic — Duplicate Detection Evaluation Script
Evaluates candidate duplicate pairs against ground truth labels across 4 methods:
1. keyword_match: Jaccard word token overlap
2. geo_only: Spatial proximity baseline (<= 200m)
3. text_only: Multilingual embedding cosine similarity
4. text_plus_geo: Combined weighted score (0.6 text + 0.4 geo)

Outputs metrics report via ml.evaluate.eval_template.
"""
import os
import sys
import csv
from typing import Dict, Any, List

# Ensure project root is in path
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from services.ai.embeddings import compute_text_embedding, cosine_similarity
from ml.evaluate.eval_template import generate_eval_report

def _compute_metrics(y_true: List[int], y_pred: List[int]) -> Dict[str, float]:
    tp = sum(1 for yt, yp in zip(y_true, y_pred) if yt == 1 and yp == 1)
    fp = sum(1 for yt, yp in zip(y_true, y_pred) if yt == 0 and yp == 1)
    fn = sum(1 for yt, yp in zip(y_true, y_pred) if yt == 1 and yp == 0)
    tn = sum(1 for yt, yp in zip(y_true, y_pred) if yt == 0 and yp == 0)

    precision = round(tp / (tp + fp), 4) if (tp + fp) > 0 else 0.0
    recall = round(tp / (tp + fn), 4) if (tp + fn) > 0 else 0.0
    f1 = round(2 * precision * recall / (precision + recall), 4) if (precision + recall) > 0 else 0.0

    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "total_pairs": len(y_true)
    }

def jaccard_word_similarity(text1: str, text2: str) -> float:
    w1 = set(str(text1).lower().split())
    w2 = set(str(text2).lower().split())
    if not w1 or not w2:
        return 0.0
    intersection = w1.intersection(w2)
    union = w1.union(w2)
    return len(intersection) / len(union)

def evaluate_duplicate_pairs(csv_path: str, output_dir: str = None) -> Dict[str, Any]:
    """
    Reads labelled pairs CSV and evaluates all 4 methods.
    """
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Pairs CSV not found: {csv_path}")

    pairs = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row.get("issue_a") or not row.get("issue_b"):
                continue
            is_dup = int(str(row.get("is_duplicate", "0")).strip())
            dist_m = float(row.get("distance_meters") or 0.0)
            text_a = str(row.get("text_a") or "")
            text_b = str(row.get("text_b") or "")
            pairs.append({
                "issue_a": row["issue_a"],
                "issue_b": row["issue_b"],
                "is_duplicate": is_dup,
                "distance_meters": dist_m,
                "text_a": text_a,
                "text_b": text_b
            })

    if not pairs:
        print("[EvalDuplicates] No labelled pairs found in CSV. Empty template provided.")
        return {"error": "empty_dataset", "sample_count": 0}

    y_true = [p["is_duplicate"] for p in pairs]

    # 1. Method: keyword_match (threshold >= 0.40)
    pred_keyword = [1 if jaccard_word_similarity(p["text_a"], p["text_b"]) >= 0.40 else 0 for p in pairs]

    # 2. Method: geo_only (distance <= 200m)
    pred_geo = [1 if p["distance_meters"] <= 200.0 else 0 for p in pairs]

    # 3. Method: text_only (embedding cosine similarity >= 0.70)
    embeddings = {}
    for p in pairs:
        if p["text_a"] not in embeddings:
            embeddings[p["text_a"]] = compute_text_embedding(p["text_a"])
        if p["text_b"] not in embeddings:
            embeddings[p["text_b"]] = compute_text_embedding(p["text_b"])

    pred_text = []
    pred_combined = []

    for p in pairs:
        t_sim = cosine_similarity(embeddings[p["text_a"]], embeddings[p["text_b"]])
        pred_text.append(1 if t_sim >= 0.70 else 0)

        # 4. Method: text + geo
        geo_score = max(0.0, 1.0 - (p["distance_meters"] / 200.0))
        comb_score = (0.60 * t_sim) + (0.40 * geo_score)
        if p["distance_meters"] <= 25.0:
            comb_score = min(1.0, comb_score + 0.10)
        pred_combined.append(1 if comb_score >= 0.60 else 0)

    metrics = {
        "keyword_match": _compute_metrics(y_true, pred_keyword),
        "geo_only": _compute_metrics(y_true, pred_geo),
        "text_only": _compute_metrics(y_true, pred_text),
        "text_plus_geo": _compute_metrics(y_true, pred_combined)
    }

    report_path = generate_eval_report(
        task_name="duplicate_detection",
        dataset_path=csv_path,
        metrics=metrics,
        model_version="v2.0-geo-embed",
        output_dir=output_dir,
        extra_metadata={"sample_count": len(pairs), "data_source": "labelled_pairs"}
    )

    return {
        "report_path": report_path,
        "metrics": metrics,
        "sample_count": len(pairs)
    }

if __name__ == "__main__":
    target_csv = sys.argv[1] if len(sys.argv) > 1 else os.path.join(_PROJECT_ROOT, "ml", "datasets", "duplicate_pairs_template.csv")
    res = evaluate_duplicate_pairs(target_csv)
    print(res)

