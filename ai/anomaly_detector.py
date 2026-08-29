"""
SmartCivic AI — Issue Frequency Anomaly Detector
Detects statistical anomalies in issue reporting rates per category per community.
Uses Z-score over rolling 7-day windows.
"""
import math
from datetime import datetime, timedelta
from bson import ObjectId
from collections import defaultdict


def _mean_std(values: list) -> tuple:
    if not values:
        return 0.0, 0.0
    n = len(values)
    mean = sum(values) / n
    variance = sum((x - mean) ** 2 for x in values) / n
    return mean, math.sqrt(variance)


def detect_anomalies(community_id: str, lookback_days: int = 30) -> list:
    """
    Detect unusual spikes in issue reporting per category using Z-score.
    
    Compares the last 7-day window against the prior lookback_days baseline.
    Z-score > 2.0 = anomaly.
    
    Returns list of anomaly objects sorted by severity.
    """
    from app import db

    cid = ObjectId(community_id)
    now = datetime.utcnow()
    baseline_start = now - timedelta(days=lookback_days)
    window_start = now - timedelta(days=7)

    all_issues = list(db.issues.find({
        "community_id": cid,
        "created_at": {"$gte": baseline_start},
        "status": {"$ne": "rejected"}
    }, {"category": 1, "created_at": 1}))

    # Group counts by category per day
    by_cat_day = defaultdict(lambda: defaultdict(int))
    for iss in all_issues:
        cat = iss.get("category", "other")
        day = iss["created_at"].date().isoformat()
        by_cat_day[cat][day] += 1

    anomalies = []
    categories = list(by_cat_day.keys())

    for cat in categories:
        day_counts = by_cat_day[cat]

        # Build 7-day buckets
        baseline_counts = []
        window_count = 0

        d = baseline_start.date()
        while d < now.date():
            count = day_counts.get(d.isoformat(), 0)
            if d >= window_start.date():
                window_count += count
            else:
                baseline_counts.append(count)
            d += timedelta(days=1)

        if len(baseline_counts) < 7:
            continue  # Not enough data for baseline

        mean, std = _mean_std(baseline_counts)

        if std == 0:
            # No variance in baseline — check for sudden appearance
            if window_count > 2:
                z_score = 3.0
            else:
                continue
        else:
            # Normalise window count to daily rate
            daily_window_rate = window_count / 7.0
            z_score = (daily_window_rate - mean) / std

        if z_score >= 2.0:
            severity = "HIGH" if z_score >= 3.0 else "MEDIUM"
            anomalies.append({
                "category": cat,
                "z_score": round(z_score, 2),
                "baseline_daily_avg": round(mean, 2),
                "recent_7d_total": window_count,
                "severity": severity,
                "message": (
                    f"Unusual spike in '{cat}' reports: {window_count} in last 7 days "
                    f"vs baseline avg {round(mean, 2)}/day (Z={round(z_score, 2)})"
                )
            })

    return sorted(anomalies, key=lambda x: x["z_score"], reverse=True)
