"""Provider-independent evidence-aware complaint priority scoring."""

from __future__ import annotations

from collections.abc import Mapping


MODEL_VERSION = "evidence-aware-v1"
SEVERITY_POINTS = {"low": 10.0, "medium": 20.0, "high": 30.0, "critical": 40.0}
URGENCY_POINTS = {"low": 0.0, "normal": 8.0, "high": 15.0, "immediate": 20.0}
SAFETY_POINTS = {"low": 0.0, "medium": 10.0, "high": 20.0, "critical": 20.0}


def _number(value, default=0.0):
    try:
        return max(0.0, min(float(value), 1.0))
    except (TypeError, ValueError):
        return default


def _independent_sources(sources, reporter_id=None):
    independent = []
    seen = set()
    reporter = str(reporter_id) if reporter_id is not None else None
    for source in sources or []:
        if not isinstance(source, Mapping):
            continue
        source_id = source.get("source_id") or source.get("citizen_id")
        if source_id is None:
            continue
        source_id = str(source_id)
        if source_id == reporter or source_id in seen:
            continue
        seen.add(source_id)
        independent.append({
            "source_id": source_id,
            "source_type": str(source.get("source_type") or "community_confirmation"),
        })
    return independent


def evaluate_priority(features: Mapping) -> dict:
    """Score structured complaint evidence; missing evidence never lowers the score."""
    features = features if isinstance(features, Mapping) else {}
    severity = str(features.get("severity") or "").strip().lower()
    urgency = str(features.get("urgency") or "normal").strip().lower()
    safety = features.get("safety_impact")
    safety_key = str(safety).strip().lower() if isinstance(safety, str) else None
    if safety_key in SAFETY_POINTS:
        safety_score = SAFETY_POINTS[safety_key]
    else:
        safety_score = _number(safety) * 20.0

    image_available = bool(features.get("image_available", False))
    location_available = bool(features.get("location_available", False))
    sources = _independent_sources(
        features.get("corroborating_sources"), features.get("reporter_id")
    )

    contributions = {
        "severity": SEVERITY_POINTS.get(severity, 0.0),
        "urgency": URGENCY_POINTS.get(urgency, URGENCY_POINTS["normal"]),
        "safety_impact": safety_score,
        "independent_corroboration": min(float(len(sources)) * 5.0, 20.0),
    }
    score = round(min(sum(contributions.values()), 100.0), 2)
    tier = "P1" if score >= 75 else "P2" if score >= 50 else "P3" if score >= 25 else "P4"

    reasons = [
        {"code": key, "contribution": value}
        for key, value in contributions.items()
    ]
    missing_evidence = []
    if not image_available:
        missing_evidence.append("image")
        reasons.append({"code": "image_not_provided", "contribution": 0.0})
    if not location_available:
        missing_evidence.append("location")
        reasons.append({"code": "location_not_provided", "contribution": 0.0})

    human_review_required = (
        severity not in SEVERITY_POINTS
        or not location_available
        or _number(features.get("confidence"), 1.0) < 0.5
    )
    if human_review_required:
        reasons.append({"code": "human_review_required", "contribution": 0.0})

    normalized_features = {
        "severity": severity or None,
        "urgency": urgency,
        "safety_impact": safety_key if safety_key in SAFETY_POINTS else _number(safety),
        "confidence": _number(features.get("confidence"), 1.0),
        "image_available": image_available,
        "location_available": location_available,
        "corroborating_sources": sources,
    }
    return {
        "score": score,
        "priority_tier": tier,
        "reasons": reasons,
        "human_review_required": human_review_required,
        "missing_evidence": missing_evidence,
        "model_version": MODEL_VERSION,
        "input_features": normalized_features,
    }