"""Run the fixed CEFAP-baseline and evidence-aware ranking comparison."""

import argparse
import csv
import hashlib
import json
import math
import sys
from datetime import datetime as RealDateTime
from pathlib import Path
from unittest.mock import patch

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services import cefap_pipeline
from services.evidence_priority import evaluate_priority

DATASET = Path(__file__).with_name("priority_dataset.csv")
DEFAULT_OUTPUT = Path(__file__).with_name("results")
FROZEN_NOW = RealDateTime(2025, 1, 1)


class FrozenDateTime(RealDateTime):
    @classmethod
    def utcnow(cls):
        return FROZEN_NOW


def _read_dataset(path):
    raw_bytes = path.read_bytes()
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row["vote_count"] = int(row["vote_count"])
        row["history_count"] = int(row["history_count"])
        row["image_available"] = row["image_available"].lower() == "true"
        row["location_available"] = row["location_available"].lower() == "true"
        row["confidence"] = float(row["confidence"])
        row["target_priority_score"] = float(row["target_priority_score"])
        row["corroborating_source_ids"] = [
            source.strip() for source in row["corroborating_source_ids"].split(";") if source.strip()
        ]
    return rows, hashlib.sha256(raw_bytes).hexdigest()


def _historical_records(row):
    created_at = RealDateTime.fromisoformat(row["created_at"])
    return [
        {"created_at": created_at - cefap_pipeline.timedelta(days=days)}
        for days in range(1, row["history_count"] + 1)
    ]


def _predict_baselines(rows):
    predictions = {name: [] for name in ("M1_text_only", "M2_text_image", "M3_plus_location", "M4_no_reliability")}
    with patch.object(cefap_pipeline, "datetime", FrozenDateTime):
        for row in rows:
            image = row["image_severity"] or None
            created_at = RealDateTime.fromisoformat(row["created_at"])
            sla_deadline = RealDateTime.fromisoformat(row["sla_deadline"])
            historical = _historical_records(row)
            methods = (
                cefap_pipeline.baseline_m1(row["severity"]),
                cefap_pipeline.baseline_m2(row["severity"], image),
                cefap_pipeline.baseline_m3(row["severity"], image, row["location_type"]),
                cefap_pipeline.baseline_m4(
                    row["severity"], image, row["location_type"], row["vote_count"],
                    historical, created_at, sla_deadline,
                ),
            )
            for method, result in zip(predictions, methods):
                predictions[method].append(round(float(result["cips"]) * 100.0, 4))
    return predictions


def _predict_proposed(rows):
    predictions = []
    for row in rows:
        sources = [{"source_id": source} for source in row["corroborating_source_ids"]]
        result = evaluate_priority({
            "severity": row["severity"],
            "urgency": row["urgency"],
            "safety_impact": row["safety_impact"],
            "confidence": row["confidence"],
            "image_available": row["image_available"],
            "location_available": row["location_available"],
            "reporter_id": row["reporter_id"],
            "corroborating_sources": sources,
        })
        predictions.append(result["score"])
    return predictions


def _metrics(actual, predicted):
    errors = [prediction - target for target, prediction in zip(actual, predicted)]
    pair_count = 0
    concordant = 0.0
    for left in range(len(actual)):
        for right in range(left + 1, len(actual)):
            actual_delta = actual[left] - actual[right]
            predicted_delta = predicted[left] - predicted[right]
            if actual_delta == 0 or predicted_delta == 0:
                if actual_delta == predicted_delta:
                    concordant += 1.0
                elif actual_delta == 0 or predicted_delta == 0:
                    concordant += 0.5
            elif actual_delta * predicted_delta > 0:
                concordant += 1.0
            pair_count += 1
    return {
        "mae": round(sum(abs(error) for error in errors) / len(errors), 4),
        "rmse": round(math.sqrt(sum(error * error for error in errors) / len(errors)), 4),
        "pairwise_rank_concordance": round(concordant / pair_count, 4) if pair_count else 0.0,
    }


def run_experiment(dataset_path=DATASET, output_dir=DEFAULT_OUTPUT):
    rows, dataset_sha256 = _read_dataset(Path(dataset_path))
    if not rows:
        raise ValueError("The fixed priority dataset must contain at least one record.")
    actual = [row["target_priority_score"] for row in rows]
    predictions = _predict_baselines(rows)
    predictions["evidence_aware_v1"] = _predict_proposed(rows)

    results = {
        "dataset": str(Path(dataset_path).name),
        "dataset_sha256": dataset_sha256,
        "record_count": len(rows),
        "score_scale": "0-100; CEFAP CIPS scores multiplied by 100",
        "time_reference": FROZEN_NOW.isoformat(),
        "metrics": {},
        "predictions": {},
    }
    for method, scores in predictions.items():
        results["metrics"][method] = _metrics(actual, scores)
        results["predictions"][method] = [
            {"case_id": row["case_id"], "target": target, "score": score}
            for row, target, score in zip(rows, actual, scores)
        ]

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = output_dir / "metrics.json"
    plot_path = output_dir / "priority_scores.png"
    metrics_path.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _plot_results(actual, predictions, results["metrics"], plot_path)
    return metrics_path, plot_path, results


def _plot_results(actual, predictions, metrics, path):
    method_names = list(predictions)
    figure, (score_axis, metric_axis) = plt.subplots(1, 2, figsize=(14, 6), constrained_layout=True)
    for method in method_names:
        score_axis.scatter(actual, predictions[method], label=method, alpha=0.8)
    score_axis.plot([0, 100], [0, 100], color="black", linestyle="--", linewidth=1, label="perfect agreement")
    score_axis.set(xlim=(0, 100), ylim=(0, 100), xlabel="Reference priority score", ylabel="Predicted score", title="Scores on the fixed dataset")
    score_axis.grid(alpha=0.25)
    score_axis.legend(fontsize=8)

    method_labels = [name.replace("_", "\n") for name in method_names]
    mae_values = [metrics[name]["mae"] for name in method_names]
    metric_axis.bar(method_labels, mae_values, color=["#26736b", "#d28b36", "#547a9e", "#9e5b51", "#536b42"])
    metric_axis.set(ylabel="Mean absolute error (lower is better)", title="Error by method")
    metric_axis.grid(axis="y", alpha=0.25)
    figure.suptitle("Complaint priority method comparison")
    figure.savefig(path, dpi=160)
    plt.close(figure)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    metrics_path, plot_path, results = run_experiment(args.dataset, args.output_dir)
    print(f"Dataset SHA-256: {results['dataset_sha256']}")
    print(f"Metrics: {metrics_path}")
    print(f"Plot: {plot_path}")
    for method, values in results["metrics"].items():
        print(f"{method}: MAE={values['mae']:.4f}, RMSE={values['rmse']:.4f}, rank={values['pairwise_rank_concordance']:.4f}")


if __name__ == "__main__":
    main()