"""
services/cefap_pipeline.py
==========================
CEFAP — Confidence-Aware Civic Evidence Fusion and Adaptive Priority

Research contribution for SmartCivic IEEE paper.

Computes:  CIPS = E × [wₛS + wᵢI + wₗL + w꜀C + wᵣR + wₜT]

This module is called from services/ai_pipeline.py as the final
decision stage. It does not replace Gemini or existing routing logic.
It replaces only the final priority calculation step.
"""

import math
import json
from datetime import datetime, timedelta

# ── Constants ─────────────────────────────────────────────────────────────────

DEFAULT_WEIGHTS = {
    "wS": 0.25,   # text severity
    "wI": 0.20,   # image severity
    "wL": 0.20,   # location impact
    "wC": 0.15,   # corroboration (crowdsourcing)
    "wR": 0.10,   # historical recurrence
    "wT": 0.10,   # SLA / time risk
}

AWLRF_LEARNING_RATE    = 0.01   # gradient step size
AWLRF_MIN_FEEDBACK     = 30     # minimum events before using learned weights
CTVE_THRESHOLD         = 0.40   # disagreement that triggers re-verification request
CORROBORATION_K        = 0.30   # saturation constant: C = 1 - e^(-kN)
RECURRENCE_LAMBDA      = 0.02   # decay constant: contribution halves ~every 35 days
RECURRENCE_WINDOW_DAYS = 90     # look-back window for recurrence
RECURRENCE_MAX         = 5.0    # normalisation denominator

PRIORITY_THRESHOLDS = {"P0": 0.85, "P1": 0.65, "P2": 0.40}

SEVERITY_MAP = {
    "critical": 1.0, "high": 0.75, "medium": 0.50, "low": 0.25, "unknown": 0.10
}

LOCATION_IMPACT_MAP = {
    "hospital": 1.0, "emergency": 1.0, "fire_station": 1.0,
    "police_station": 0.90, "school": 0.80, "college": 0.80,
    "public_building": 0.75, "main_road": 0.70, "highway": 0.70,
    "metro_station": 0.65, "bus_stop": 0.60, "commercial": 0.55,
    "market": 0.55, "park": 0.45, "residential": 0.30,
    "lane": 0.25, "unknown": 0.40,
}

MONSOON_MULTIPLIERS = {
    "flooding": 1.40, "roads": 1.20, "trees": 1.30,
    "electricity": 1.20, "solid_waste": 1.10,
    "public_health": 1.15, "water": 0.90,
}

# ── Signal functions ──────────────────────────────────────────────────────────

def _sev(severity):
    """Severity label or float → 0.0–1.0"""
    if isinstance(severity, (int, float)):
        return max(0.0, min(float(severity), 1.0))
    return SEVERITY_MAP.get(str(severity or "unknown").lower(), 0.10)

def _img(image_severity, image_confidence):
    """Image evidence → dict or None (None = missing, not zero)"""
    if image_severity is None or image_confidence is None:
        return None
    return {
        "score":      _sev(image_severity),
        "confidence": max(0.0, min(float(image_confidence), 1.0)),
    }

def _loc(location_type):
    """Location type → 0.0–1.0"""
    return LOCATION_IMPACT_MAP.get(str(location_type or "unknown").lower(), 0.40)

def _corr(vote_count):
    """Crowd votes → 0.0–1.0 (saturating: C = 1 - e^{-kN})"""
    n = max(0, int(vote_count or 0))
    return 1.0 - math.exp(-CORROBORATION_K * n)

def _recur(historical_complaints):
    """Recent recurrences → 0.0–1.0 (time-decayed sum)"""
    if not historical_complaints:
        return 0.0
    now = datetime.utcnow()
    total = 0.0
    for c in historical_complaints:
        ts = c.get("created_at")
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts)
            except ValueError:
                continue
        if not isinstance(ts, datetime):
            continue
        days = (now - ts).total_seconds() / 86400
        if days <= RECURRENCE_WINDOW_DAYS:
            total += math.exp(-RECURRENCE_LAMBDA * days)
    return min(total / RECURRENCE_MAX, 1.0)

def _sla(created_at, sla_deadline=None):
    """Elapsed / allowed → 0.0–1.5 (>1.0 means overdue)"""
    if isinstance(created_at, str):
        try:
            created_at = datetime.fromisoformat(created_at)
        except ValueError:
            created_at = datetime.utcnow()
    now     = datetime.utcnow()
    elapsed = (now - created_at).total_seconds()
    if sla_deadline:
        if isinstance(sla_deadline, str):
            try:
                sla_deadline = datetime.fromisoformat(sla_deadline)
            except ValueError:
                sla_deadline = None
    allowed = (
        (sla_deadline - created_at).total_seconds()
        if sla_deadline else 72 * 3600
    )
    return min(elapsed / max(allowed, 1), 1.5)

def _reliability(text_severity_score, text_confidence, image_evidence):
    """
    E = C_avg × (1 - D)

    Missing image → D=0, no penalty.
    Large disagreement → CTVE fires (targeted re-verification request).
    """
    if image_evidence is None:
        c_avg        = max(0.0, min(float(text_confidence or 0), 1.0))
        disagreement = 0.0
        ctve         = False
        ctve_msg     = None
    else:
        img_s        = image_evidence["score"]
        img_c        = image_evidence["confidence"]
        c_avg        = (float(text_confidence or 0) + img_c) / 2.0
        disagreement = abs(text_severity_score - img_s)
        ctve         = disagreement > CTVE_THRESHOLD
        if ctve:
            if text_severity_score > img_s:
                ctve_msg = (
                    "Your description suggests a serious issue, but the uploaded "
                    "image appears to show a minor problem. Could you upload a "
                    "clearer photo, or confirm your description is accurate?"
                )
            else:
                ctve_msg = (
                    "The uploaded image appears to show a serious problem, but your "
                    "description sounds minor. Could you describe the severity in "
                    "more detail?"
                )
        else:
            ctve_msg = None

    E = max(0.01, min(c_avg * (1.0 - disagreement), 1.0))
    return {
        "E": E, "disagreement": disagreement,
        "ctve_triggered": ctve, "ctve_message": ctve_msg,
    }

def _monsoon(service, dt=None):
    d = dt or datetime.utcnow()
    if 6 <= d.month <= 9:
        mult = MONSOON_MULTIPLIERS.get(str(service or "").lower(), 1.05)
        return {"active": True, "multiplier": mult}
    return {"active": False, "multiplier": 1.0}

def _priority(cips, monsoon_active):
    shift = 0.08 if monsoon_active else 0.0
    if cips >= PRIORITY_THRESHOLDS["P0"] - shift: return "P0"
    if cips >= PRIORITY_THRESHOLDS["P1"] - shift: return "P1"
    if cips >= PRIORITY_THRESHOLDS["P2"] - shift: return "P2"
    return "P3"

# ── Weight management (AWLRF) ─────────────────────────────────────────────────

def get_weights(db, ward_id):
    try:
        if db is not None:
            row = db.cefap_weights.find_one({"ward_id": ward_id})
            if row and row.get("feedback_count", 0) >= AWLRF_MIN_FEEDBACK:
                return {k: row[k] for k in DEFAULT_WEIGHTS if k in row}
    except Exception:
        pass
    return dict(DEFAULT_WEIGHTS)

def _norm(w):
    t = sum(w.values())
    if t == 0: return dict(DEFAULT_WEIGHTS)
    return {k: v/t for k,v in w.items()}

def _clamp(w, lo=0.02, hi=0.60):
    return {k: max(lo, min(v, hi)) for k,v in w.items()}

# ── Main CEFAP stage ──────────────────────────────────────────────────────────

def cefap_stage(db, params):
    """
    Call this from services/ai_pipeline.py AFTER Gemini analysis,
    BEFORE returning the final result to the route.
    """
    try:
        service    = params.get("service", "unknown_other")
        created_at = params.get("created_at", datetime.utcnow())
        ward_id    = params.get("ward_id")

        # Step 1: signals
        S  = _sev(params.get("text_severity", "low"))
        ie = _img(params.get("image_severity"), params.get("image_confidence"))
        I  = ie["score"] if ie else None
        L  = _loc(params.get("location_type"))
        C  = _corr(params.get("vote_count", 0))
        R  = _recur(params.get("historical_complaints", []))
        T  = min(_sla(created_at, params.get("sla_deadline")), 1.0)

        # Step 2: reliability + CTVE
        rel = _reliability(S, params.get("text_confidence", 0.5), ie)
        E   = rel["E"]

        # Step 3: weights
        w = get_weights(db, ward_id)
        ew = dict(w)
        if I is None:
            ew["wS"] = w["wS"] + w["wI"]
            ew["wI"] = 0.0
            I_val = 0.0
        else:
            I_val = I

        # Step 4: weighted sum
        ws = (ew["wS"]*S + ew["wI"]*I_val + ew["wL"]*L +
              ew["wC"]*C + ew["wR"]*R + ew["wT"]*T)

        # Step 5: apply reliability
        cips = E * ws

        # Step 6: monsoon
        m    = _monsoon(service, created_at)
        cips = round(min(max(cips * m["multiplier"], 0.0), 1.0), 3)

        # Step 7: priority
        p    = _priority(cips, m["active"])

        # Step 8: verification flag
        vr = (
            rel["ctve_triggered"] or
            params.get("text_confidence", 0) < 0.70 or
            (0.60 < cips < 0.70)
        )

        result = {
            "cips":                 cips,
            "priority":             p,
            "evidence_reliability": E,
            "evidence_agreement":   round(1.0 - rel["disagreement"], 3),
            "disagreement":         round(rel["disagreement"], 3),
            "ctve_triggered":       rel["ctve_triggered"],
            "ctve_message":         rel["ctve_message"],
            "verification_required":vr,
            "signals": {
                "text_severity":   S, "image_severity": I,
                "location_impact": L, "corroboration":   C,
                "recurrence":      R, "sla_risk":        T,
            },
            "weights": ew,
            "monsoon": m,
        }

        # Step 9: persist (non-fatal)
        _persist(db, params.get("issue_id"), ward_id, result, E)
        return result
    except Exception as exc:
        return {
            "cips": 0.50,
            "priority": "P2",
            "evidence_reliability": 0.50,
            "evidence_agreement": 0.50,
            "disagreement": 0.0,
            "ctve_triggered": False,
            "ctve_message": None,
            "verification_required": True,
            "signals": {
                "text_severity": 0.5, "image_severity": None,
                "location_impact": 0.4, "corroboration": 0.0,
                "recurrence": 0.0, "sla_risk": 0.5
            },
            "weights": DEFAULT_WEIGHTS,
            "monsoon": {"active": False, "multiplier": 1.0},
            "fallback_reason": str(exc)
        }


def _persist(db, issue_id, ward_id, result, E):
    if not issue_id or db is None:
        return
    try:
        db.cefap_results.update_one(
            {"issue_id": str(issue_id)},
            {"$set": {
                "issue_id":             str(issue_id),
                "ward_id":              ward_id,
                "cips_score":           result["cips"],
                "priority":             result["priority"],
                "text_severity":        result["signals"]["text_severity"],
                "image_severity":       result["signals"]["image_severity"],
                "location_impact":      result["signals"]["location_impact"],
                "corroboration":        result["signals"]["corroboration"],
                "recurrence":           result["signals"]["recurrence"],
                "sla_risk":             result["signals"]["sla_risk"],
                "evidence_reliability": E,
                "disagreement":         result["disagreement"],
                "weights_snapshot":     json.dumps(result["weights"]),
                "monsoon_active":       result["monsoon"]["active"],
                "computed_at":          datetime.utcnow(),
            }},
            upsert=True
        )
    except Exception:
        pass


# ── AWLRF feedback ────────────────────────────────────────────────────────────

def record_resolution_feedback(db, issue_id, ward_id, predicted_priority,
                                resolved_at, created_at,
                                escalation_level=0, officer_overrides=0,
                                citizen_confirmed=False):
    """
    Call this from the resolution route after closing a complaint.
    Updates ward-specific CEFAP weights from real resolution behaviour.
    Non-fatal — never raises an exception.
    """
    try:
        if db is None:
            return
        stored = db.cefap_results.find_one({"issue_id": str(issue_id)})
        if not stored:
            return

        actual    = _actual_urgency(created_at, resolved_at,
                                    escalation_level, officer_overrides,
                                    citizen_confirmed)
        pred      = {"P0":0.95,"P1":0.75,"P2":0.50,"P3":0.25}.get(
                        predicted_priority, 0.25)
        error     = pred - actual
        current   = get_weights(db, ward_id)
        E         = stored.get("evidence_reliability", 0.5)

        new_w = {
            "wS": current["wS"] - AWLRF_LEARNING_RATE*error*E*stored.get("text_severity", 0),
            "wI": current["wI"] - AWLRF_LEARNING_RATE*error*E*(stored.get("image_severity") or 0),
            "wL": current["wL"] - AWLRF_LEARNING_RATE*error*E*stored.get("location_impact", 0),
            "wC": current["wC"] - AWLRF_LEARNING_RATE*error*E*stored.get("corroboration", 0),
            "wR": current["wR"] - AWLRF_LEARNING_RATE*error*E*stored.get("recurrence", 0),
            "wT": current["wT"] - AWLRF_LEARNING_RATE*error*E*stored.get("sla_risk", 0),
        }
        final = _clamp(_norm(new_w))

        db.cefap_weights.update_one(
            {"ward_id": ward_id},
            {"$set": {**final, "last_updated": datetime.utcnow()},
             "$inc": {"feedback_count": 1}},
            upsert=True
        )
        db.cefap_feedback.insert_one({
            "issue_id":           str(issue_id),
            "ward_id":            ward_id,
            "predicted_priority": predicted_priority,
            "predicted_score":    pred,
            "actual_urgency":     actual,
            "error":              error,
            "weights_snapshot":   json.dumps(final),
            "created_at":         datetime.utcnow(),
        })
    except Exception:
        pass


def _actual_urgency(created_at, resolved_at, escalation_level,
                    officer_overrides, citizen_confirmed):
    for dt in [created_at, resolved_at]:
        if isinstance(dt, str):
            try:
                dt = datetime.fromisoformat(dt)
            except ValueError:
                pass
    try:
        hours = max((resolved_at - created_at).total_seconds() / 3600, 0)
    except Exception:
        hours = 48
    if   hours <= 1:  ts = 0.95
    elif hours <= 4:  ts = 0.85
    elif hours <= 24: ts = 0.70
    elif hours <= 72: ts = 0.50
    else:             ts = 0.25
    boost = (min(escalation_level*0.10, 0.30) +
             min(officer_overrides*0.05, 0.15) +
             (0.05 if citizen_confirmed else -0.05))
    return min(max(ts + boost, 0.0), 1.0)


# ── Ablation baselines (for paper experiments) ────────────────────────────────

def baseline_m1(text_severity):
    """M1: text severity only."""
    s = _sev(text_severity)
    return {"cips": s, "priority": _priority(s, False), "model": "M1_text_only"}

def baseline_m2(text_severity, image_severity):
    """M2: text + image average, no reliability."""
    s = _sev(text_severity)
    i = _sev(image_severity) if image_severity else s
    c = (s + i) / 2 if image_severity else s
    return {"cips": c, "priority": _priority(c, False), "model": "M2_text_image"}

def baseline_m3(text_severity, image_severity, location_type):
    """M3: text + image + location, fixed weights, no reliability."""
    s = _sev(text_severity)
    i = _sev(image_severity) if image_severity else s
    l = _loc(location_type)
    c = s*0.40 + (i*0.30 if image_severity else 0) + l*0.30
    return {"cips": round(c,3), "priority": _priority(c, False), "model": "M3_+location"}

def baseline_m4(text_severity, image_severity, location_type,
                vote_count, historical, created_at, sla_deadline):
    """M4: all 6 signals, fixed weights, NO evidence reliability factor."""
    s = _sev(text_severity); i = _sev(image_severity) if image_severity else 0
    l = _loc(location_type); c = _corr(vote_count)
    r = _recur(historical);  t = min(_sla(created_at, sla_deadline), 1.0)
    dw = DEFAULT_WEIGHTS
    ws = dw["wS"]*s + dw["wI"]*i + dw["wL"]*l + dw["wC"]*c + dw["wR"]*r + dw["wT"]*t
    return {"cips": round(min(ws,1),3), "priority": _priority(ws,False), "model": "M4_no_reliability"}
