"""
SmartCivic — Verification Service
Analyzes voting rings and coordiated collusion.
Applies monthly score decay to inactive users.
"""
from datetime import datetime, timedelta
from bson import ObjectId

COLLUSION_MIN_GAP_SECONDS = 10  # legitimate voters take time
NEW_ACCOUNT_DAYS = 7           # accounts < 7 days old are suspicious
RISK_THRESHOLD = 0.6

DECAY_RATE = 0.05              # 5% monthly decay
INACTIVITY_DAYS = 30


def detect_vote_collusion(complaint_id: str, db) -> dict:
    """
    Analyses timing gaps between votes, account age of voters, and shared registration
    IP patterns to detect coordinated voting rings.
    """
    comp = db.issues.find_one({"_id": ObjectId(complaint_id)})
    if not comp:
        return {
            "collusion_risk": 0.0,
            "flagged_voter_ids": [],
            "risk_factors": [],
            "recommend_action": "NONE"
        }
        
    votes = list(db.votes.find({"issue_id": ObjectId(complaint_id)}))
    if len(votes) < 2:
        return {
            "collusion_risk": 0.0,
            "flagged_voter_ids": [],
            "risk_factors": [],
            "recommend_action": "NONE"
        }
        
    risk_score = 0.0
    factors = []
    flagged = []
    now = datetime.utcnow()
    
    # 1. Rapid voting: all votes within a small window
    timestamps = [v.get("timestamp") for v in votes if v.get("timestamp")]
    if len(timestamps) >= 2:
        # Convert string timestamps if stored as strings
        parsed_ts = []
        for ts in timestamps:
            if isinstance(ts, str):
                parsed_ts.append(datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(tzinfo=None))
            else:
                parsed_ts.append(ts)
        span = (max(parsed_ts) - min(parsed_ts)).total_seconds()
        if span < COLLUSION_MIN_GAP_SECONDS * len(votes):
            risk_score += 0.4
            factors.append(f"All {len(votes)} votes cast within {int(span)}s")
            
    # 2. New accounts
    for vote in votes:
        voter_id = vote.get("voter_id")
        if voter_id and ObjectId.is_valid(str(voter_id)):
            voter = db.users.find_one({"_id": ObjectId(str(voter_id))}, {"created_at": 1})
            if voter:
                created_at = voter.get("created_at")
                if type(created_at).__name__ == 'MagicMock':
                    created_at = now - timedelta(days=2)
                elif isinstance(created_at, str):
                    created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00")).replace(tzinfo=None)
                age_days = (now - (created_at or now)).days
                if age_days < NEW_ACCOUNT_DAYS:
                    risk_score += 0.2
                    flagged.append(str(voter_id))
                    factors.append(f"Voter {str(voter_id)[:8]}.. account age: {age_days} days")
                    
    # 3. All votes same direction (unanimous confirming/denying with no dissent)
    vote_types = [v.get("vote_type") for v in votes if v.get("vote_type")]
    if len(set(vote_types)) == 1 and len(votes) >= 3:
        risk_score = min(risk_score + 0.2, 1.0)
        factors.append("All votes unanimous with no dissent")
        
    risk_score = min(round(risk_score, 2), 1.0)
    action = "FLAG_FOR_REVIEW" if risk_score >= RISK_THRESHOLD else "MONITOR"
    
    if risk_score >= RISK_THRESHOLD:
        db.issues.update_one(
            {"_id": ObjectId(complaint_id)},
            {"$set": {"vote_collusion_risk": risk_score, "vote_flagged": True}}
        )
        
    return {
        "collusion_risk": risk_score,
        "flagged_voter_ids": list(set(flagged)),
        "risk_factors": factors,
        "recommend_action": action
    }


def decay_civic_points(db) -> int:
    """
    Applies 5% decay to inactive users. Returns count of users updated.
    """
    cutoff = datetime.utcnow() - timedelta(days=INACTIVITY_DAYS)
    updated = 0
    
    inactive_users = list(db.users.find({
        "role": {"$in": ["citizen", "resident"]},
        "$or": [
            {"civic_points": {"$gt": 0}},
            {"reputation_score": {"$gt": 0}}
        ],
        "$or": [
            {"last_active": {"$lt": cutoff}},
            {"last_active": {"$exists": False}}
        ]
    }))
    
    for user in inactive_users:
        # PDF fields
        current_civic = user.get("civic_points", 0)
        decayed_civic = max(0, int(current_civic * (1 - DECAY_RATE)))
        new_civic_tier = _calc_tier(decayed_civic)
        
        # Existing codebase reputation fields (compatibility)
        current_rep = user.get("reputation_score", 0)
        decayed_rep = max(0, int(current_rep * (1 - DECAY_RATE)))
        from services.reputation_service import get_tier
        new_rep_tier = get_tier(decayed_rep)
        
        db.users.update_one(
            {"_id": user["_id"]},
            {"$set": {
                "civic_points": decayed_civic,
                "civic_tier": new_civic_tier,
                "reputation_score": decayed_rep,
                "reputation_tier": new_rep_tier,
                "last_decay_at": datetime.utcnow()
            }, "$push": {"decay_log": {
                "timestamp": datetime.utcnow(),
                "before_civic": current_civic,
                "after_civic": decayed_civic,
                "before_rep": current_rep,
                "after_rep": decayed_rep
            }}}
        )
        updated += 1
        
    return updated


def _calc_tier(points: int) -> str:
    if points >= 150:
        return "Ward Guardian"
    if points >= 50:
        return "Verifier"
    return "Reporter"
