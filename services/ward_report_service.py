"""
SmartCivic — Ward Monthly Report Service
Aggregates monthly performance reports for a ward.
"""
from datetime import datetime
import calendar
from bson import ObjectId
from ai.analytics import compute_worker_performance


def generate_ward_monthly_report(ward: str, month: int, year: int, db) -> dict:
    """
    Returns a fully structured monthly report dict for the given ward.
    """
    # 1. Resolve community / ward filter
    community_id = None
    if isinstance(ward, str) and ObjectId.is_valid(ward):
        community_id = ObjectId(ward)
    else:
        # Try to find community by name matching ward
        comm = db.communities.find_one({"name": {"$regex": ward, "$options": "i"}})
        if comm:
            community_id = comm["_id"]
            
    # Date boundaries
    start = datetime(year, month, 1)
    end = datetime(year, month, calendar.monthrange(year, month)[1], 23, 59, 59)
    
    # Construct base filter supporting both 'ward' and 'community_id'
    base_filter = {"created_at": {"$gte": start, "$lte": end}}
    if community_id:
        base_filter["community_id"] = community_id
    else:
        # Try finding using 'ward' or 'community_name'
        base_filter["$or"] = [{"ward": ward}, {"community_name": ward}]

    # Total complaints
    total = db.issues.count_documents(base_filter)
    
    # Resolved complaints (lowercase or uppercase)
    resolved = db.issues.count_documents({
        **base_filter,
        "status": {"$in": ["resolved", "RESOLVED"]}
    })
    
    # SLA Met complaints (lowercase, uppercase or sla_breached not True)
    sla_ok = db.issues.count_documents({
        **base_filter,
        "$or": [
            {"sla_status": {"$in": ["MET", "met"]}},
            {"sla_breached": {"$ne": True}}
        ]
    })
    
    # Reopened complaints (lowercase or uppercase)
    reopened = db.issues.count_documents({
        **base_filter,
        "status": {"$in": ["reopened", "REOPENED"]}
    })
    
    # By category
    category_pipeline = [
        {"$match": base_filter},
        {"$group": {"_id": "$category", "count": {"$sum": 1}}}
    ]
    by_category = {}
    try:
        agg_results = list(db.issues.aggregate(category_pipeline))
        by_category = {r["_id"]: r["count"] for r in agg_results if r["_id"]}
    except Exception:
        pass
        
    # Average resolution time
    resolved_comps = list(db.issues.find(
        {
            **base_filter,
            "status": {"$in": ["resolved", "RESOLVED"]},
            "resolved_at": {"$exists": True}
        },
        {"created_at": 1, "resolved_at": 1}
    ))
    
    if resolved_comps:
        hours = []
        for c in resolved_comps:
            c_at = c.get("created_at")
            r_at = c.get("resolved_at")
            if c_at and r_at:
                if isinstance(c_at, str):
                    c_at = datetime.fromisoformat(c_at.replace("Z", "+00:00")).replace(tzinfo=None)
                if isinstance(r_at, str):
                    r_at = datetime.fromisoformat(r_at.replace("Z", "+00:00")).replace(tzinfo=None)
                hours.append((r_at - c_at).total_seconds() / 3600)
        avg_resolution_hours = round(sum(hours) / len(hours), 1) if hours else None
    else:
        avg_resolution_hours = None
        
    # Trust score for this ward
    trust_score = None
    trust_level = None
    try:
        # Check ward_trust or trust_scorer
        trust_rec = db.ward_trust.find_one({"ward": ward}, sort=[("computed_at", -1)])
        if not trust_rec and community_id:
            # Fall back to checking by community_id
            trust_rec = db.ward_trust.find_one({"community_id": community_id}, sort=[("computed_at", -1)])
        if trust_rec:
            trust_score = trust_rec.get("trust_score")
            trust_level = trust_rec.get("trust_level") or trust_rec.get("grade")
    except Exception:
        pass
        
    # Fallback to computing in real-time if not found
    if trust_score is None:
        try:
            from ai.trust_scorer import compute_trust_score
            target_cid = community_id or ObjectId("660000000000000000000001")
            res = compute_trust_score(str(target_cid))
            trust_score = res.get("trust_score")
            trust_level = res.get("grade")
        except Exception:
            pass

    # Top 3 workers by performance
    # Workers are users with role = 'field_worker' in the community
    worker_filter = {"role": "field_worker"}
    if community_id:
        worker_filter["community_id"] = community_id
    else:
        worker_filter["ward"] = ward
        
    workers = list(db.users.find(worker_filter))
    scored_workers = []
    for w in workers:
        perf = compute_worker_performance(str(w["_id"]), db)
        scored_workers.append({
            "worker_id": str(w["_id"]),
            "name": w.get("name"),
            "performance_score": perf.get("score", 0)
        })
    scored_workers.sort(key=lambda x: x["performance_score"], reverse=True)
    
    return {
        "ward": ward,
        "period": f"{year}-{str(month).zfill(2)}",
        "generated_at": datetime.utcnow().isoformat(),
        "totals": {
            "complaints_filed": total,
            "resolved": resolved,
            "resolution_rate_pct": round(resolved / max(total, 1) * 100, 1),
            "sla_compliance_pct": round(sla_ok / max(total, 1) * 100, 1),
            "reopened": reopened,
            "avg_resolution_hours": avg_resolution_hours,
        },
        "by_category": by_category,
        "trust": {"score": trust_score, "level": trust_level},
        "top_workers": scored_workers[:3],
    }
