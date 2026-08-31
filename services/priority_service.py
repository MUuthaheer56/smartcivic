"""
SmartCivic+ — Priority Score Calculation Service
Computes weighted importance scores (0-100) per issue.
"""
from datetime import datetime
from bson import ObjectId

SEVERITY_WEIGHTS = {
    "critical": 40,
    "high": 30,
    "medium": 20,
    "low": 10
}

SLA_RISK_WEIGHTS = {
    "breached": 30,
    "urgent": 20,
    "warning": 10,
    "on_track": 0
}

def calculate_priority(issue: dict, db) -> float:
    """
    Priority Score = weighted sum of severity, age, duplicates, location, and SLA risk.
    Returns a float clamped between 0.0 and 100.0.
    """
    score = 0.0
    
    # 1. Severity weight (10 to 40)
    sev = issue.get("severity", "medium").lower()
    score += SEVERITY_WEIGHTS.get(sev, 20)
    
    # 2. Complaint age weight (capped at 20)
    created_at = issue.get("created_at")
    if created_at:
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00")).replace(tzinfo=None)
        hours_old = (datetime.utcnow() - created_at).total_seconds() / 3600
        score += min(hours_old * 0.5, 20.0)
        
    # 3. Duplicate count weight (capped at 20)
    report_count = 1
    cluster_id = issue.get("cluster_id")
    if cluster_id:
        cluster = db.clusters.find_one({"_id": ObjectId(cluster_id)})
        if cluster:
            report_count = cluster.get("report_count", 1)
    else:
        # Check duplicate list
        dup_children = issue.get("duplicate_children", [])
        if dup_children:
            report_count = len(dup_children) + 1
            
    score += min(report_count * 2, 20)
    
    # 4. Location importance (+10 each for school/hospital proximity)
    text = (issue.get("description", "") + " " + issue.get("address", "")).lower()
    if any(k in text for k in ["school", "college", "university", "academy", "kindergarten"]):
        score += 10.0
    if any(k in text for k in ["hospital", "clinic", "medical center", "pharmacy"]):
        score += 10.0
        
    # 5. SLA risk weight (0 to 30)
    sla_status = issue.get("sla_status", "on_track").lower()
    score += SLA_RISK_WEIGHTS.get(sla_status, 0)
    
    return min(max(score, 0.0), 100.0)
