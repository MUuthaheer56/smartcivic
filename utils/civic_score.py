"""
SmartCivic — CivicScore & Reputation Tier Engine
"""
from datetime import datetime
from bson import ObjectId

TIER_THRESHOLDS = {"reporter": 0, "verifier": 50, "ward_guardian": 200}

SCORE_DELTAS = {
    "report_filed":       5,
    "verification_made": 10,
    "false_report":     -20,
    "report_resolved":    3,
}

def compute_tier(score: int) -> str:
    if score >= TIER_THRESHOLDS["ward_guardian"]: return "ward_guardian"
    if score >= TIER_THRESHOLDS["verifier"]:      return "verifier"
    return "reporter"

def apply_score_delta(db, user_id, reason: str):
    delta = SCORE_DELTAS.get(reason, 0)
    if delta == 0 or not user_id:
        return None
    try:
        user = db.users.find_one({"_id": ObjectId(user_id)}, {"civic_score": 1})
        if not user:
            return None
        raw_score = user.get("civic_score")
        current_score = int(raw_score) if raw_score is not None and str(raw_score).isdigit() else 0
        new_score = max(0, current_score + delta)
        new_tier  = compute_tier(new_score)
        db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {
                "civic_score": new_score,
                "tier":        new_tier,
                "role_tier":   new_tier,
                "updated_at":  datetime.utcnow(),
            }}
        )
        return new_score, new_tier
    except Exception:
        return None
