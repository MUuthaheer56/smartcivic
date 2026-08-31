"""
SmartCivic+ — CivicPulse Temporal Decay Prediction Model
=========================================================
Novel feature: predicts infrastructure segment failure date BEFORE any citizen reports it.

Algorithm:
  1. For each infrastructure segment, collect its health score samples over time
     (sourced from complaint events linked to the segment).
  2. Fit an exponential decay curve:   H(t) = H0 * e^(-λt)
     where H0 = initial health (100), λ = decay constant derived from observed data.
  3. Solve for t* where H(t*) = FAILURE_THRESHOLD (default 30).
     t* = ln(H0 / FAILURE_THRESHOLD) / λ
  4. Store the predicted failure date and a risk band in `db.civicpulse_predictions`.
  5. Expose a proactive maintenance queue sorted by days_until_failure ascending.

Dependencies: only stdlib + pymongo. No scipy/numpy required.
"""

import math
import logging
from datetime import datetime, timedelta
from app import db

logger = logging.getLogger("smartcivic_json")

# Below this health score the segment is considered failed / in critical need of maintenance
FAILURE_THRESHOLD = 30

# Minimum number of complaint events needed to fit a curve (avoid overfitting on 1 data point)
MIN_EVENTS_FOR_PREDICTION = 3

# Default λ when insufficient data — conservatively assumes ~180-day decay to threshold
DEFAULT_LAMBDA = -math.log(FAILURE_THRESHOLD / 100.0) / 180.0


def _fit_decay_lambda(events: list) -> float:
    """
    Fits λ from a list of (days_since_first_complaint, health_score) tuples using
    ordinary least-squares on the linearised form: ln(H) = ln(H0) - λt
    so ln(H/H0) = -λt  →  λ = -mean(ln(H/100) / t)   for t > 0.

    Falls back to DEFAULT_LAMBDA if any sample is degenerate.
    """
    H0 = 100.0
    estimates = []
    for (t, h) in events:
        if t <= 0 or h <= 0 or h >= H0:
            continue
        try:
            lam = -math.log(h / H0) / t
            if lam > 0:
                estimates.append(lam)
        except (ValueError, ZeroDivisionError):
            continue

    if not estimates:
        return DEFAULT_LAMBDA

    return sum(estimates) / len(estimates)


def _predict_failure_days(lam: float) -> float:
    """
    Returns days from now until health reaches FAILURE_THRESHOLD.
    t* = ln(H0 / threshold) / λ
    """
    try:
        return math.log(100.0 / FAILURE_THRESHOLD) / lam
    except (ValueError, ZeroDivisionError):
        return 365.0  # default: flag in a year if λ is degenerate


def _build_health_timeline(segment_id: str) -> list:
    """
    Reconstructs a synthetic health-score timeline from complaint events linked
    to this segment, sorted ascending by created_at.

    Returns list of (days_elapsed: float, estimated_health: int) tuples.

    Health estimation per event:
      - Each unresolved complaint deducts 5 points
      - Each resolved complaint (closed) adds 3 points (repair effect)
      - Each SLA breach adds an extra -4 points
      - Each recurrence adds -8 points
    Cumulative score is clamped to [5, 100].
    """
    issues = list(
        db.issues.find({"infrastructure_segment_id": segment_id})
        .sort("created_at", 1)
    )

    if not issues:
        return []

    first_at = issues[0].get("created_at") or datetime.utcnow()
    running_health = 100.0
    timeline = []

    for issue in issues:
        created_at = issue.get("created_at") or first_at
        days = max(0.0, (created_at - first_at).total_seconds() / 86400.0)
        status = issue.get("status", "submitted")

        if status in ("closed",):
            running_health += 3.0   # repair credit
        else:
            running_health -= 5.0   # unresolved complaint

        if issue.get("sla_status") == "breached":
            running_health -= 4.0

        if issue.get("is_recurring"):
            running_health -= 8.0

        running_health = max(5.0, min(100.0, running_health))
        timeline.append((days, running_health))

    return timeline


def compute_civicpulse_predictions() -> list:
    """
    Main entry point — called by the APScheduler weekly job.

    For each infrastructure segment:
      1. Build health timeline from linked issues.
      2. If enough events: fit λ, predict failure date, assign risk band.
      3. If too few events: use DEFAULT_LAMBDA (conservative estimate).
      4. Upsert prediction into db.civicpulse_predictions.

    Returns list of prediction dicts for the caller to inspect or log.
    """
    logger.info('{"log_type": "civicpulse", "msg": "Starting CivicPulse prediction sweep"}')
    segments = list(db.infrastructure.find({}))

    if not segments:
        logger.info('{"log_type": "civicpulse", "msg": "No infrastructure segments found — skipping"}')
        return []

    now = datetime.utcnow()
    predictions = []

    for seg in segments:
        segment_id = seg.get("segment_id", str(seg["_id"]))
        timeline = _build_health_timeline(segment_id)

        if len(timeline) >= MIN_EVENTS_FOR_PREDICTION:
            lam = _fit_decay_lambda(timeline)
            data_quality = "fitted"
        else:
            lam = DEFAULT_LAMBDA
            data_quality = "estimated"

        days_until_failure = _predict_failure_days(lam)
        predicted_failure_date = now + timedelta(days=days_until_failure)

        # Current estimated health (last point in timeline, or 100 if no events)
        current_health = int(timeline[-1][1]) if timeline else seg.get("health_score", 100)

        # Risk band
        if days_until_failure <= 14:
            risk_band = "CRITICAL"
        elif days_until_failure <= 45:
            risk_band = "HIGH"
        elif days_until_failure <= 90:
            risk_band = "MEDIUM"
        else:
            risk_band = "LOW"

        pred = {
            "segment_id": segment_id,
            "segment_type": seg.get("segment_type"),
            "name": seg.get("name"),
            "ward": seg.get("ward"),
            "current_health": current_health,
            "decay_lambda": round(lam, 6),
            "days_until_failure": round(days_until_failure, 1),
            "predicted_failure_date": predicted_failure_date,
            "risk_band": risk_band,
            "data_quality": data_quality,   # "fitted" or "estimated"
            "event_count": len(timeline),
            "computed_at": now,
        }

        # Upsert so repeated runs update rather than accumulate
        db.civicpulse_predictions.update_one(
            {"segment_id": segment_id},
            {"$set": pred},
            upsert=True
        )
        predictions.append(pred)

    logger.info(
        f'{{"log_type": "civicpulse", "msg": "Sweep complete", "segments": {len(predictions)}}}'
    )
    return predictions


def get_proactive_maintenance_queue(ward: str = None, limit: int = 20) -> list:
    """
    Returns the top `limit` segments most urgently needing proactive maintenance,
    sorted by days_until_failure ascending (soonest failure first).

    Filters to a specific ward if provided.
    Only returns segments with risk_band != "LOW" unless fewer than `limit` exist.
    """
    query = {}
    if ward:
        query["ward"] = ward

    # Prefer non-LOW risk; fall back to all if the result set would be empty
    priority_query = {**query, "risk_band": {"$in": ["CRITICAL", "HIGH", "MEDIUM"]}}
    cursor = db.civicpulse_predictions.find(
        priority_query, {"_id": 0}
    ).sort("days_until_failure", 1).limit(limit)

    results = list(cursor)
    if not results:
        # Fallback: return whatever exists (all LOW risk)
        results = list(
            db.civicpulse_predictions.find(query, {"_id": 0})
            .sort("days_until_failure", 1)
            .limit(limit)
        )

    return results


def get_segment_prediction(segment_id: str) -> dict:
    """
    Returns the stored prediction for a single segment, or None if not computed yet.
    """
    return db.civicpulse_predictions.find_one({"segment_id": segment_id}, {"_id": 0})
