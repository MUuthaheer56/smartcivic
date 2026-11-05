"""
SmartCivic — Disagreement Analysis Script
Summarises classification disagreement between Local Model, Gemini, and Officer Corrections per class.
Reads from db.ai_decisions and db.ai_corrections.
Outputs report to ml/reports/disagreement_summary.json.

RULE R9 & R10 COMPLIANCE:
Audits shadow-mode outputs against officer ground-truth labels.
"""
import os
import sys

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import json
import argparse
from datetime import datetime
from typing import Dict, Any, List
from collections import defaultdict


def generate_disagreement_report(
    mongo_uri: str = None,
    output_path: str = "ml/reports/disagreement_summary.json"
) -> Dict[str, Any]:
    try:
        from app import create_app, db
        app = create_app()
    except Exception as e:
        print(f"[Disagreement Report] Could not initialize app/db: {e}")
        db = None

    if db is None:
        report = {
            "evaluated_at": datetime.utcnow().isoformat(),
            "total_evaluated_issues": 0,
            "overall_agreement_rate": 1.0,
            "per_class_summary": {},
            "officer_corrections_count": 0,
            "status": "db_unavailable"
        }
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        return report

    with app.app_context():
        # Query local text decisions and gemini text decisions
        local_decisions = list(db.ai_decisions.find({"stage": "local_text"}))
        gemini_decisions = list(db.ai_decisions.find({"stage": "gemini_text"}))
        corrections = list(db.ai_corrections.find({"field_changed": {"$in": ["category", "service", "priority"]}}))

        gemini_by_issue = {str(d.get("issue_id")): d for d in gemini_decisions}
        corr_by_issue = defaultdict(list)
        for c in corrections:
            corr_by_issue[str(c.get("issue_id"))].append(c)

        total_pairs = 0
        agreed_count = 0
        per_class = defaultdict(lambda: {"total": 0, "agreed": 0, "disagreed": 0, "officer_overrides": 0})
        disagreements = []

        for loc in local_decisions:
            issue_id = str(loc.get("issue_id"))
            gem = gemini_by_issue.get(issue_id)
            if not gem:
                continue

            total_pairs += 1
            loc_val = loc.get("envelope", {}).get("value", {})
            gem_val = gem.get("envelope", {}).get("value", {})

            loc_svc = str(loc_val.get("service") or loc_val.get("category") or "other").lower()
            gem_svc = str(gem_val.get("category") or gem_val.get("service") or "other").lower()

            per_class[gem_svc]["total"] += 1
            if loc_svc == gem_svc:
                agreed_count += 1
                per_class[gem_svc]["agreed"] += 1
            else:
                per_class[gem_svc]["disagreed"] += 1
                disagreements.append({
                    "issue_id": issue_id,
                    "gemini_class": gem_svc,
                    "local_class": loc_svc,
                    "has_officer_correction": issue_id in corr_by_issue
                })

            if issue_id in corr_by_issue:
                per_class[gem_svc]["officer_overrides"] += 1

        overall_agreement = round(agreed_count / total_pairs, 4) if total_pairs > 0 else 1.0

        class_summary = {}
        for cls, counts in per_class.items():
            tot = counts["total"]
            agr = counts["agreed"]
            class_summary[cls] = {
                "total": tot,
                "agreed": agr,
                "disagreed": counts["disagreed"],
                "agreement_rate": round(agr / tot, 3) if tot > 0 else 1.0,
                "officer_overrides": counts["officer_overrides"]
            }

        report = {
            "evaluated_at": datetime.utcnow().isoformat(),
            "total_evaluated_issues": total_pairs,
            "overall_agreement_rate": overall_agreement,
            "per_class_summary": class_summary,
            "officer_corrections_analyzed": len(corrections),
            "sample_disagreements": disagreements[:10]
        }

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

        print(f"\n[Disagreement Report] Saved to {output_path}")
        print(f"  Paired Decisions Evaluated: {total_pairs}")
        print(f"  Overall Agreement Rate:     {overall_agreement * 100:.1f}%")
        print(f"  Officer Corrections Found:  {len(corrections)}")
        return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate AI Disagreement Analysis")
    parser.add_argument("--out", default="ml/reports/disagreement_summary.json")
    args = parser.parse_args()
    generate_disagreement_report(output_path=args.out)

