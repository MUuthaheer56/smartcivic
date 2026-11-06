"""
scripts/eval_cefap_agreement.py - Evaluates CEFAP Baselines (M1-M5) Against Human Annotations
Reads: results/cefap_label_sheet.csv (filled with human labels P0, P1, P2, P3 across labelers)
Computes:
1. Tier agreement rate (%) for M1..M5 against human consensus
2. Weighted Cohen's Kappa (linear/quadratic)
3. Spearman rank correlation against mean human rank
4. P0 / P1 recall (safety critical coverage)
"""
import os
import sys
import csv
import argparse
import numpy as np
from scipy import stats
from sklearn.metrics import cohen_kappa_score

# Add root directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.cefap_pipeline import (
    baseline_m1, baseline_m2, baseline_m3, baseline_m4, cefap_stage
)
from services.ai_service import analyze_complaint_text
from datetime import datetime, timedelta

PRIORITY_TO_NUM = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
NUM_TO_PRIORITY = {0: "P0", 1: "P1", 2: "P2", 3: "P3"}


def evaluate_human_labels(csv_path: str):
    if not os.path.exists(csv_path):
        print(f"[ERROR] Label sheet '{csv_path}' does not exist.")
        sys.exit(1)

    rows = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)

    if not rows:
        print("[ERROR] Label sheet is empty.")
        sys.exit(1)

    # Validate whether labels exist
    labeled_rows = []
    for r in rows:
        label = (r.get("consensus_priority") or r.get("labeler_1_priority") or "").strip().upper()
        if label in PRIORITY_TO_NUM:
            labeled_rows.append((r, label))

    if not labeled_rows:
        print(f"[WAITING] No human labels found in '{csv_path}'.")
        print("Please annotate 'consensus_priority' or 'labeler_1_priority' with P0, P1, P2, or P3 for the scenarios.")
        return None

    print(f"[*] Found {len(labeled_rows)} / {len(rows)} labeled scenarios. Computing metrics for M1..M5...")

    y_human = []
    m_preds = {"M1": [], "M2": [], "M3": [], "M4": [], "M5": []}
    m_cips = {"M1": [], "M2": [], "M3": [], "M4": [], "M5": []}

    now = datetime.utcnow()
    sla = now + timedelta(hours=24)

    for r, h_label in labeled_rows:
        y_human.append(PRIORITY_TO_NUM[h_label])
        desc = r["description"]
        svc = r.get("service", "roads")
        loc = r.get("location_type", "residential")

        # Run text analysis to extract severity
        txt_res = analyze_complaint_text(desc)
        sev = txt_res.get("severity", "medium")

        # M1
        res1 = baseline_m1(sev)
        m_preds["M1"].append(PRIORITY_TO_NUM.get(res1["priority"], 2))
        m_cips["M1"].append(res1["cips"])

        # M2
        res2 = baseline_m2(sev, None)
        m_preds["M2"].append(PRIORITY_TO_NUM.get(res2["priority"], 2))
        m_cips["M2"].append(res2["cips"])

        # M3
        res3 = baseline_m3(sev, None, loc)
        m_preds["M3"].append(PRIORITY_TO_NUM.get(res3["priority"], 2))
        m_cips["M3"].append(res3["cips"])

        # M4
        res4 = baseline_m4(sev, None, loc, 0, [], now, sla)
        m_preds["M4"].append(PRIORITY_TO_NUM.get(res4["priority"], 2))
        m_cips["M4"].append(res4["cips"])

        # M5 (Full CEFAP)
        res5 = cefap_stage(None, {
            "service": svc,
            "text_severity": sev,
            "image_severity": None,
            "image_confidence": 0.0,
            "location_type": loc,
            "vote_count": 0,
            "historical_complaints": [],
            "created_at": now,
            "sla_deadline": sla
        })
        m_preds["M5"].append(PRIORITY_TO_NUM.get(res5["priority"], 2))
        m_cips["M5"].append(res5["cips"])

    y_human = np.array(y_human)

    # Human rank (0 is highest priority P0, so rank directly)
    # Higher CIPS means higher priority, so invert CIPS rank to correlate with priority tier
    print("\n==========================================================================")
    print(f" CEFAP Agreement Evaluation on Human Annotations (N = {len(labeled_rows)})")
    print("==========================================================================")
    print(f"{'Model':<8} | {'Tier Agree (%)':<15} | {'Weighted Kappa':<15} | {'Spearman Rho':<15} | {'P0/P1 Recall':<15}")
    print("-" * 75)

    report = {}
    for m in ["M1", "M2", "M3", "M4", "M5"]:
        preds = np.array(m_preds[m])
        cips = np.array(m_cips[m])

        # Exact tier agreement
        agree = np.mean(preds == y_human) * 100.0

        # Quadratic weighted Cohen's Kappa
        try:
            kappa = cohen_kappa_score(y_human, preds, weights="quadratic")
        except Exception:
            kappa = 0.0

        # Spearman correlation between predicted CIPS and human numeric tier
        # Invert human tier so P0 (0) is highest value 3
        human_urgency = 3 - y_human
        rho, _ = stats.spearmanr(cips, human_urgency)

        # High-priority Recall (P0 & P1)
        high_mask = (y_human <= 1)
        if np.any(high_mask):
            pred_high = (preds[high_mask] <= 1)
            high_recall = np.mean(pred_high) * 100.0
        else:
            high_recall = 100.0

        print(f"{m:<8} | {agree:<15.2f} | {kappa:<15.4f} | {rho:<15.4f} | {high_recall:<15.2f}")
        report[m] = {
            "tier_agreement_pct": round(agree, 2),
            "weighted_cohen_kappa": round(kappa, 4),
            "spearman_rho": round(rho, 4),
            "high_priority_recall_pct": round(high_recall, 2)
        }
    print("==========================================================================")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CEFAP Agreement Evaluator")
    parser.add_argument("--sheet", default="results/cefap_label_sheet.csv", help="Path to label sheet CSV")
    args = parser.parse_args()
    evaluate_human_labels(args.sheet)

