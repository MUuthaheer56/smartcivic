from bson import ObjectId

TIER_THRESHOLDS = {
    'Newcomer': 0,
    'Active Resident': 20,
    'Civic Champion': 50,
    'Community Hero': 100
}

def get_tier(score: int) -> str:
    current_tier = 'Newcomer'
    # Sort tiers by threshold ascending
    sorted_tiers = sorted(TIER_THRESHOLDS.items(), key=lambda x: x[1])
    for tier, threshold in sorted_tiers:
        if score >= threshold:
            current_tier = tier
    return current_tier

def award_reputation(user_id: str, points: int, reason: str):
    from app import db
    from services.notification_service import notify_user
    
    user = db.users.find_one({'_id': ObjectId(user_id)})
    if not user:
        return
        
    old_score = user.get('reputation_score', 0)
    new_score = old_score + points
    
    old_tier = user.get('reputation_tier', 'Newcomer')
    new_tier = get_tier(new_score)
    
    update_data = {
        'reputation_score': new_score,
        'reputation_tier': new_tier
    }
    
    db.users.update_one(
        {'_id': ObjectId(user_id)},
        {'$set': update_data}
    )
    
    # Notify user of points award
    notify_user(
        user_id=user_id,
        message=f"You earned +{points} reputation points for: {reason}.",
        notif_type="reputation_gain"
    )
    
    # Notify user of tier promotion if it changes
    if old_tier != new_tier:
        notify_user(
            user_id=user_id,
            message=f"Congratulations! You've been promoted to {new_tier}!",
            notif_type="tier_promotion"
        )
