"""
SmartCivic v2 — AI Impact Prediction Service
Predicts multidimensional civic impact (road damage, safety, traffic, resident impact, worsening risk)
and outputs structured summary for officer review.
"""
from datetime import datetime

def predict_impact(complaint: dict, image_severity: float = 0.0) -> dict:
    """
    Evaluates impact metrics using complaint metadata and visual evidence score.
    """
    sev = complaint.get("severity", "medium").lower()
    service = complaint.get("service", "roads").lower()
    support_count = complaint.get("support_count", 0)

    month = datetime.utcnow().month
    is_monsoon = 6 <= month <= 9

    # Compute risk levels based on severity, service, and visual evidence
    if sev == "critical" or complaint.get("emergency"):
        road_risk = "critical" if service in ["roads", "water", "flooding"] else "high"
        safety_risk = "critical"
        traffic_impact = "high" if service in ["roads", "traffic", "electricity"] else "medium"
        resident_impact = "critical"
        worsening_risk = "high"
        recommended_priority = "P0" if complaint.get("emergency") else "P1"
        summary = "CRITICAL RISK: Potential life safety hazard or severe infrastructure impairment requiring immediate dispatch."
    elif sev == "high":
        road_risk = "high" if service in ["roads", "water", "drainage"] else "medium"
        safety_risk = "high" if service in ["electricity", "trees", "flooding"] else "medium"
        traffic_impact = "high" if service in ["roads", "traffic"] else "medium"
        resident_impact = "high" if support_count >= 5 else "medium"
        worsening_risk = "high" if is_monsoon else "medium"
        recommended_priority = "P1" if support_count >= 10 else "P2"
        summary = "HIGH IMPACT: High likelihood of worsening or secondary damage if unaddressed within SLA timeframe."
    elif sev == "medium":
        road_risk = "medium" if image_severity > 5.0 else "low"
        safety_risk = "medium" if service == "electricity" else "low"
        traffic_impact = "medium" if service in ["roads", "traffic"] else "low"
        resident_impact = "medium" if support_count >= 3 else "low"
        worsening_risk = "medium" if is_monsoon else "low"
        recommended_priority = "P2" if support_count >= 5 else "P3"
        summary = "MODERATE IMPACT: Standard operational priority. Scheduled for ward field team intervention."
    else: # low
        road_risk = "low"
        safety_risk = "low"
        traffic_impact = "low"
        resident_impact = "low"
        worsening_risk = "low"
        recommended_priority = "P3"
        summary = "LOW IMPACT: Routine maintenance request with minimal safety risk."

    return {
        "road_damage_risk": road_risk,
        "safety_risk": safety_risk,
        "traffic_impact": traffic_impact,
        "resident_impact": resident_impact,
        "worsening_risk": worsening_risk,
        "recommended_priority": recommended_priority,
        "impact_summary": summary,
    }

def infer_location_type(complaint: dict) -> str:
    desc = (complaint.get("description", "") + " " + complaint.get("location_text", "")).lower()
    if any(w in desc for w in ["main road", "highway", "national", "state highway", "arterial"]):
        return "main_road"
    if any(w in desc for w in ["lane", "bylane", "cross", "alley"]):
        return "lane"
    return "residential_road"
