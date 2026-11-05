"""
SmartCivic — Standard Evaluation Report Generator Template
Reads a labelled dataset file, computes metrics, records the dataset SHA256 checksum,
captures current git commit hash, and writes a committed JSON report to ml/reports/.
"""
import os
import sys
import json
import hashlib
import subprocess
from datetime import datetime
from typing import Dict, Any, List

def compute_file_sha256(path: str) -> str:
    """Computes SHA256 hex digest of a dataset file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def get_git_commit() -> str:
    """Retrieves current Git commit hash or 'unknown'."""
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL
        ).decode("utf-8").strip()
        return commit
    except Exception:
        return "unknown"

def generate_eval_report(
    task_name: str,
    dataset_path: str,
    metrics: Dict[str, Any],
    model_version: str,
    output_dir: str = None,
    extra_metadata: Dict[str, Any] = None
) -> str:
    """
    Produces a standard JSON evaluation report and writes it to ml/reports/.
    Returns the path of the created report file.
    """
    if not os.path.exists(dataset_path):
        raise FileNotFoundError(f"Dataset file not found: {dataset_path}")

    dataset_hash = compute_file_sha256(dataset_path)
    git_commit = get_git_commit()
    timestamp = datetime.utcnow().isoformat()

    report_data = {
        "task_name": task_name,
        "model_version": model_version,
        "timestamp_utc": timestamp,
        "git_commit": git_commit,
        "dataset": {
            "path": os.path.basename(dataset_path),
            "sha256": dataset_hash,
            "sample_count": extra_metadata.get("sample_count") if extra_metadata else None,
            "data_source": extra_metadata.get("data_source", "ground_truth") if extra_metadata else "ground_truth"
        },
        "metrics": metrics,
        "metadata": extra_metadata or {}
    }

    if output_dir is None:
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "reports"))
        output_dir = base_dir

    os.makedirs(output_dir, exist_ok=True)
    report_filename = f"eval_{task_name}_{model_version}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    report_path = os.path.join(output_dir, report_filename)

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2)

    print(f"[EvalReport] Saved evaluation report to: {report_path}")
    return report_path

if __name__ == "__main__":
    print("Evaluation Template ready. Import and call generate_eval_report() in your eval scripts.")

