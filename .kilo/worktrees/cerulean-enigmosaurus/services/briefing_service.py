"""
SmartCivic+ — Officer Briefing & Ward Health Score Service
Generates, caches, and schedules briefings and health scores using MongoDB.
"""
from datetime import datetime, timedelta
from bson import ObjectId
from app import db
from services import ai_service

def get_cached_briefing() -> dict:
    """
    Returns the most recent cached briefing.
    If no briefing exists or it is older than 1 hour, regenerate it.
    """
    briefing = db.briefings.find_one({}, sort=[("generated_at", -1)])
    now = datetime.utcnow()
    
    if not briefing or (now - briefing.get("generated_at", now)) > timedelta(hours=1):
        return regenerate_briefing()
        
    return briefing

def regenerate_briefing() -> dict:
    """
    Computes current metrics, finds top duplicate clusters, builds rule-based recommendations,
    and calls Gemini to generate a natural language briefing.
    """
    print("[Briefing Service] Regenerating daily officer briefing...")
    
    # Calculate stats
    emergency_count = db.issues.count_documents({"is_emergency": True, "status": {"$nin": ["closed", "rejected"]}})
    sla_breached_count = db.issues.count_documents({"sla_status": "breached", "status": {"$nin": ["closed", "rejected"]}})
    sla_warning_count = db.issues.count_documents({"sla_status": "warning", "status": {"$nin": ["closed", "rejected"]}})
    
    available_workers = db.users.count_documents({"role": "worker", "is_available": True})
    pending_assignments = db.issues.count_documents({"status": "officer_reviewed", "worker_id": None})
    
    # Top cluster summary
    top_cluster = db.clusters.find_one({"status": "open"}, sort=[("report_count", -1)])
    top_cluster_summary = "None"
    if top_cluster:
        top_cluster_summary = f"Cluster in {top_cluster.get('ward')} has {top_cluster.get('report_count', 0)} reports (category: {top_cluster.get('category')})."
        
    # Recommended actions (rule-based)
    recommended_actions = []
    
    # Check SLA breached issues without worker
    breached_unassigned = list(db.issues.find({
        "sla_status": "breached",
        "status": {"$in": ["submitted", "ai_reviewed", "officer_reviewed"]},
        "worker_id": None
    }, limit=3))
    for issue in breached_unassigned:
        recommended_actions.append(f"Assign worker to breached issue #{str(issue['_id'])[-6:]} ({issue.get('category')})")
        
    # Check high duplicate clusters
    high_clusters = list(db.clusters.find({"status": "open", "report_count": {"$gt": 5}}, limit=2))
    for c in high_clusters:
        # Check if centroid is assigned or resolved
        recommended_actions.append(f"Review cluster #{str(c['_id'])[-6:]} in {c.get('ward')} with {c.get('report_count')} duplicate reports.")
        
    # Check pending officer approvals
    pending_approvals = list(db.issues.find({"status": "work_completed"}, limit=2))
    for issue in pending_approvals:
        recommended_actions.append(f"Verify resolved issue #{str(issue['_id'])[-6:]} submitted by worker.")
        
    stats = {
        "emergency_count": emergency_count,
        "sla_breached_count": sla_breached_count,
        "sla_warning_count": sla_warning_count,
        "available_workers": available_workers,
        "pending_assignments": pending_assignments,
        "top_cluster_summary": top_cluster_summary,
        "recommended_actions": recommended_actions
    }
    
    briefing_text = ai_service.generate_officer_briefing(stats)
    now = datetime.utcnow()
    
    briefing_doc = {
        "briefing_text": briefing_text,
        "generated_at": now,
        "stats": stats,
        "recommended_actions": recommended_actions
    }
    
    # Store in DB (upsert into briefings collection)
    db.briefings.delete_many({}) # clear older ones
    db.briefings.insert_one(briefing_doc)
    
    return briefing_doc

def calculate_ward_health_score(ward: str) -> int:
    """
    Score = 100 minus penalties:
    - Each unresolved complaint older than 24h: -1 (max -30)
    - Each SLA breach: -3 (max -30)
    - Each recurring issue: -5 (max -20)
    - Low avg citizen rating (< 3.0): -10
    - High resolution rate (>90%): +10 bonus
    Score is clamped 0–100.
    """
    now = datetime.utcnow()
    one_day_ago = now - timedelta(days=1)
    
    # 1. Unresolved complaints > 24h
    unresolved_count = db.issues.count_documents({
        "ward": ward,
        "status": {"$nin": ["closed", "rejected"]},
        "created_at": {"$lt": one_day_ago}
    })
    unresolved_penalty = min(30, unresolved_count * 1)
    
    # 2. SLA breaches
    breach_count = db.issues.count_documents({
        "ward": ward,
        "sla_status": "breached",
        "status": {"$nin": ["closed", "rejected"]}
    })
    breach_penalty = min(30, breach_count * 3)
    
    # 3. Recurring issues
    recurring_count = db.issues.count_documents({
        "ward": ward,
        "is_recurring": True,
        "status": {"$nin": ["closed", "rejected"]}
    })
    recurring_penalty = min(20, recurring_count * 5)
    
    # 4. Low citizen ratings
    # average citizen rating in this ward
    rating_pipeline = [
        {"$match": {"ward": ward, "citizen_rating": {"$ne": None}}},
        {"$group": {"_id": "$ward", "avg": {"$avg": "$citizen_rating"}}}
    ]
    rating_results = list(db.issues.aggregate(rating_pipeline))
    rating_penalty = 0
    if rating_results and rating_results[0]["avg"] < 3.0:
        rating_penalty = 10
        
    # 5. High resolution rate bonus
    total_issues = db.issues.count_documents({"ward": ward})
    resolved_issues = db.issues.count_documents({"ward": ward, "status": "closed"})
    resolution_bonus = 0
    if total_issues > 0:
        res_rate = (resolved_issues / total_issues) * 100.0
        if res_rate > 90.0:
            resolution_bonus = 10
            
    score = 100 - unresolved_penalty - breach_penalty - recurring_penalty - rating_penalty + resolution_bonus
    score = max(0, min(100, score))
    
    # Cache ward health score
    db.ward_scores.update_one(
        {"ward": ward},
        {"$set": {
            "score": score,
            "calculated_at": now
        }},
        upsert=True
    )
    return score
