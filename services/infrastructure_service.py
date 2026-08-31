"""
SmartCivic+ — Infrastructure Health Scoring Service
Calculates health scores, aggregates deterioration indices, and links complaints.
"""
from datetime import datetime, timedelta
from bson import ObjectId
from app import db

def calculate_health_score(segment_id: str) -> int:
    """
    Score = 100 minus penalties:
    - Each unresolved complaint < 7 days: -3 (max -20)
    - Each unresolved complaint > 7 days: -5 (max -25)
    - Each SLA breach: -4 (max -20)
    - Recurrence (is_recurring == True): -10
    - Last repair > 90 days ago: -10
    - Last repair > 180 days ago: -15
    - Recent high-rated resolve (>= 4 stars): +5 (max +10)
    Clamped between 0 and 100.
    """
    segment = db.infrastructure.find_one({"segment_id": segment_id})
    if not segment:
        return 100
        
    now = datetime.utcnow()
    seven_days_ago = now - timedelta(days=7)
    
    # Linked issues
    issues = list(db.issues.find({"infrastructure_segment_id": segment_id}))
    
    unresolved_recent = 0
    unresolved_old = 0
    sla_breaches = 0
    recurrence_penalty = 0
    repair_count = 0
    last_repair_at = segment.get("last_repair_at")
    recent_high_ratings = 0
    
    for issue in issues:
        status = issue.get("status")
        created_at = issue.get("created_at") or now
        
        if status not in ["closed", "rejected"]:
            if created_at >= seven_days_ago:
                unresolved_recent += 1
            else:
                unresolved_old += 1
                
            if issue.get("sla_status") == "breached":
                sla_breaches += 1
        else:
            repair_count += 1
            rating = issue.get("citizen_rating")
            if rating and rating >= 4:
                recent_high_ratings += 1
                
        if issue.get("is_recurring"):
            recurrence_penalty = 10
            
    # Calculate penalties
    penalty_unresolved_recent = min(20, unresolved_recent * 3)
    penalty_unresolved_old = min(25, unresolved_old * 5)
    penalty_sla = min(20, sla_breaches * 4)
    
    # Repair age penalties
    repair_penalty = 0
    if last_repair_at:
        days_since_repair = (now - last_repair_at).days
        if days_since_repair > 180:
            repair_penalty = 15
        elif days_since_repair > 90:
            repair_penalty = 10
            
    # Bonus
    bonus = min(10, recent_high_ratings * 5)
    
    score = 100 - penalty_unresolved_recent - penalty_unresolved_old - penalty_sla - recurrence_penalty - repair_penalty + bonus
    score = max(0, min(100, score))
    
    # Update segment stats
    last_complaint = None
    if issues:
        issues.sort(key=lambda x: x.get("created_at") or now, reverse=True)
        last_complaint = issues[0].get("created_at")
        
    db.infrastructure.update_one(
        {"segment_id": segment_id},
        {"$set": {
            "health_score": score,
            "complaint_count": len(issues),
            "repair_count": repair_count,
            "last_complaint_at": last_complaint,
            "updated_at": now
        }}
    )
    return score

def get_infrastructure_health_overview(ward: str = None, segment_type: str = None, min_score: int = 0, max_score: int = 100) -> list:
    """
    Returns sorted list of segments worst-first.
    """
    query = {
        "health_score": {"$gte": min_score, "$lte": max_score}
    }
    if ward:
        query["ward"] = ward
    if segment_type:
        query["segment_type"] = segment_type
        
    return list(db.infrastructure.find(query).sort("health_score", 1))

def link_complaint_to_segment(issue_id):
    """
    Looks up issue's location coordinates. Finds nearest infrastructure segment within 100m.
    """
    issue = db.issues.find_one({"_id": ObjectId(issue_id)})
    if not issue or "location" not in issue:
        return None
        
    # Spatial search: find nearest segment within 100 meters
    # Requires 2dsphere index on location field
    near_query = {
        "location": {
            "$nearSphere": {
                "$geometry": issue["location"],
                "$maxDistance": 100
            }
        }
    }
    
    # Match segment_type to issue's category
    cat_type_map = {
        "road": "road",
        "water": "water",
        "electricity": "streetlight",
        "sanitation": "garbage_point",
        "drainage": "drainage"
    }
    seg_type = cat_type_map.get(issue.get("category"))
    if seg_type:
        near_query["segment_type"] = seg_type
        
    nearest = db.infrastructure.find_one(near_query)
    if nearest:
        db.issues.update_one(
            {"_id": ObjectId(issue_id)},
            {"$set": {"infrastructure_segment_id": nearest["segment_id"]}}
        )
        # Recalculate health
        calculate_health_score(nearest["segment_id"])
        return nearest["segment_id"]
        
    return None

def trigger_all_infrastructure_recalc():
    """
    Recomputes health scores for all segments in the city.
    """
    print("[Infrastructure Service] Performing health score recalculations sweep...")
    segments = list(db.infrastructure.find({}, {"segment_id": 1}))
    for seg in segments:
        try:
            calculate_health_score(seg["segment_id"])
        except Exception as e:
            print(f"[Infrastructure Service] Sweep recalculate failed for {seg.get('segment_id')}: {e}")
