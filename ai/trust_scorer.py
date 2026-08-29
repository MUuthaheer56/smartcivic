"""
SmartCivic AI — Civic Trust Score per Ward/Community
Score 0–100 based on: response speed, SLA compliance, resolution verification,
recurrence rate, community participation.
"""
from datetime import datetime, timedelta
from bson import ObjectId


def compute_trust_score(community_id: str) -> dict:
    """
    Compute a Civic Trust Score (0–100) for a community.
    
    Component weights:
      40% — SLA compliance rate (resolved before deadline)
      25% — Resolution rate (resolved / total)
      20% — Community participation (votes cast / issues reported)
      15% — Recurrence penalty (issues in same spot within 30 days)
    """
    from app import db

    cid = ObjectId(community_id)
    all_issues = list(db.issues.find({"community_id": cid}))

    if not all_issues:
        return {
            "trust_score": 100.0,
            "grade": "A",
            "components": {
                "sla_compliance_rate": 100.0,
                "resolution_rate": 100.0,
                "participation_rate": 100.0,
                "recurrence_penalty": 0.0
            },
            "computed_at": datetime.utcnow().isoformat()
        }

    total = len(all_issues)
    resolved = [i for i in all_issues if i.get("status") == "resolved"]

    # Component 1 — SLA Compliance
    sla_compliant = 0
    for iss in resolved:
        deadline = iss.get("sla_deadline")
        resolved_at = iss.get("resolved_at")
        if deadline and resolved_at:
            if isinstance(deadline, str):
                deadline = datetime.fromisoformat(deadline.replace("Z", "+00:00")).replace(tzinfo=None)
            if isinstance(resolved_at, str):
                resolved_at = datetime.fromisoformat(resolved_at.replace("Z", "+00:00")).replace(tzinfo=None)
            if resolved_at <= deadline:
                sla_compliant += 1
    sla_rate = (sla_compliant / len(resolved)) if resolved else 0.0

    # Component 2 — Resolution Rate
    resolution_rate = len(resolved) / total if total > 0 else 0.0

    # Component 3 — Participation Rate
    total_votes = sum(
        i.get("confirm_votes", 0) + i.get("deny_votes", 0) for i in all_issues
    )
    participation_rate = min(1.0, total_votes / (total * 3)) if total > 0 else 0.0

    # Component 4 — Recurrence Penalty
    from services.route_optimizer import haversine
    recurrences = 0
    cutoff = datetime.utcnow() - timedelta(days=30)
    recent = [i for i in all_issues if i.get("created_at", datetime.min) >= cutoff]
    for i, a in enumerate(recent):
        for b in recent[i + 1:]:
            if a.get("category") == b.get("category"):
                if haversine(a["lat"], a["lng"], b["lat"], b["lng"]) <= 0.1:
                    recurrences += 1
    max_possible_recurrences = max(1, len(recent))
    recurrence_penalty = min(1.0, recurrences / max_possible_recurrences)

    # Weighted score
    score = (
        (sla_rate * 40.0) +
        (resolution_rate * 25.0) +
        (participation_rate * 20.0) +
        ((1.0 - recurrence_penalty) * 15.0)
    )
    score = round(max(0.0, min(100.0, score)), 1)

    grade = "A" if score >= 80 else ("B" if score >= 60 else ("C" if score >= 40 else "D"))

    return {
        "trust_score": score,
        "grade": grade,
        "components": {
            "sla_compliance_rate": round(sla_rate * 100, 1),
            "resolution_rate": round(resolution_rate * 100, 1),
            "participation_rate": round(participation_rate * 100, 1),
            "recurrence_penalty": round(recurrence_penalty * 100, 1)
        },
        "computed_at": datetime.utcnow().isoformat()
    }
