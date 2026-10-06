"""
SmartCivic+ — What-If Simulation Engine Service
Models the hypothetical impact of crew resource additions and priority category shifts.
"""
import logging
from datetime import datetime
from bson import ObjectId
from app import db

logger = logging.getLogger(__name__)

def run_ward_simulation(db, ward: str, weather_factor: float, staff_reduction_pct: float, report_surge_pct: float) -> dict:
    """
    Executes a read-only predictive simulation assessing how operational 
    shocks (weather, reporting surges, staff shortages) affect SLA compliance 
    and workload in a given ward.
    """
    try:
        # Fetch baseline active metrics for the ward
        baseline_active = db.issues.count_documents({"location.ward": ward, "status": {"$nin": ["RESOLVED", "CLOSED"]}})
        if baseline_active == 0:
            baseline_active = db.issues.count_documents({"ward": ward, "status": {"$nin": ["RESOLVED", "CLOSED", "closed"]}})
        baseline_workers = db.users.count_documents({"role": "worker", "ward": ward, "approved_by_authority": True})
        
        if baseline_workers == 0:
            baseline_workers = 1 # Prevent division by zero

        # Simulation mathematics
        adjusted_reports = baseline_active * (1.0 + (report_surge_pct / 100.0))
        adjusted_workers = max(int(baseline_workers * (1.0 - (staff_reduction_pct / 100.0))), 1)
        weather_penalty = 1.2 if weather_factor > 0.5 else 1.0

        # Predicted outcomes
        predicted_backlog = int(adjusted_reports * weather_penalty)
        workload_per_worker = round(predicted_backlog / adjusted_workers, 2)
        
        # Predicted SLA breach increase
        sla_breach_increase_pct = max(round(((workload_per_worker - (baseline_active / baseline_workers)) / (baseline_active / baseline_workers)) * 100, 1), 0.0)

        return {
            "success": True,
            "ward": ward,
            "simulation_parameters": {
                "weather_shock": weather_factor,
                "staff_reduction_pct": staff_reduction_pct,
                "report_surge_pct": report_surge_pct
            },
            "predictions": {
                "predicted_active_backlog": predicted_backlog,
                "effective_worker_count": adjusted_workers,
                "workload_per_worker": workload_per_worker,
                "sla_breach_increase_pct": sla_breach_increase_pct,
                "system_status": "HIGH_STRESS" if sla_breach_increase_pct > 20 else "STABLE"
            }
        }
    except Exception as e:
        logger.error(f"Simulation execution failed: {e}")
        return {"success": False, "error": str(e)}


def simulate_worker_addition(ward: str, department: str, additional_workers: int) -> dict:
    """
    Estimates the impact of adding workers to a specific ward and department.
    """
    # 1. Get current open complaints in ward + department
    open_query = {
        "status": {"$nin": ["closed", "rejected"]},
        "department": department
    }
    if ward:
        open_query["ward"] = ward
        
    open_complaints_count = db.issues.count_documents(open_query)
    
    # 2. Get current avg_resolution_hours for that department (from closed issues)
    closed_pipeline = [
        {"$match": {"status": "closed", "department": department, "created_at": {"$ne": None}, "updated_at": {"$ne": None}}},
        {"$group": {
            "_id": None,
            "avg_hours": {"$avg": {"$divide": [{"$subtract": ["$updated_at", "$created_at"]}, 3600000]}}
        }}
    ]
    res_closed = list(db.issues.aggregate(closed_pipeline))
    avg_resolution_hours = round(res_closed[0]["avg_hours"], 1) if res_closed and res_closed[0]["avg_hours"] else 24.0
    
    # 3. Get current worker count assigned to ward + department
    # Map department name to possible skill aliases used in worker profiles
    _DEPT_TO_SKILLS = {
        "roads":        ["roads", "road_repair", "road"],
        "water_supply": ["water_supply", "water"],
        "electrical":   ["electrical", "electricity"],
        "sanitation":   ["sanitation"],
        "drainage":     ["drainage"],
    }
    _skill_aliases = _DEPT_TO_SKILLS.get(department, [department])
    worker_query = {"role": "worker", "skills": {"$in": _skill_aliases}}
    if ward:
        worker_query["ward"] = ward
    current_workers = db.users.count_documents(worker_query)
    if current_workers == 0:
        current_workers = 1 # avoid division by zero
        
    # 4. Calculate current throughput (complaints resolved per hour per worker)
    # Average worker clears (1 / avg_resolution_hours) complaints per hour
    worker_throughput = 1.0 / avg_resolution_hours
    
    # 5. Estimate new throughput with additional workers
    new_workers_count = current_workers + additional_workers
    estimated_throughput_total = new_workers_count * worker_throughput
    
    # 6. Calculate estimated new avg_resolution_hours and clearance time
    # New avg resolution hours is scaled down by worker ratio (diminishing returns factor of 0.9 applies for team overhead)
    scale_factor = (current_workers / new_workers_count)
    estimated_avg_resolution_hours = round(avg_resolution_hours * scale_factor * 1.1, 1)
    estimated_avg_resolution_hours = max(2.0, min(avg_resolution_hours, estimated_avg_resolution_hours))
    
    # Estimated clearance hours for open queue
    estimated_clearance_hours = round(open_complaints_count / estimated_throughput_total, 1) if estimated_throughput_total > 0 else 0.0
    
    # 7. Calculate estimated SLA compliance change
    # Get current SLA compliance
    total_issues = db.issues.count_documents({"department": department})
    breached_issues = db.issues.count_documents({"department": department, "sla_status": "breached"})
    current_sla_compliance = 100.0
    if total_issues > 0:
        current_sla_compliance = round(((total_issues - breached_issues) / total_issues) * 100.0, 1)
        
    # Estimated compliance increase is proportional to the throughput increase (capped at 99%)
    throughput_gain = (new_workers_count - current_workers) / current_workers
    estimated_sla_compliance = round(min(99.0, current_sla_compliance + (throughput_gain * 15.0)), 1)
    estimated_sla_compliance = max(current_sla_compliance, estimated_sla_compliance)
    
    return {
        "current_workers": current_workers,
        "additional_workers": additional_workers,
        "current_avg_resolution_hours": avg_resolution_hours,
        "estimated_avg_resolution_hours": estimated_avg_resolution_hours,
        "current_sla_compliance_pct": current_sla_compliance,
        "estimated_sla_compliance_pct": estimated_sla_compliance,
        "open_complaints": open_complaints_count,
        "estimated_clearance_hours": estimated_clearance_hours
    }

def simulate_category_priority_shift(prioritize_category: str) -> dict:
    """
    Estimates the impact of deprioritizing all other categories to focus on one category.
    """
    categories = ["road", "water", "electricity", "sanitation", "drainage"]
    
    # Estimate prioritized category improvement
    # Resolution time decreases by 40%
    priority_pipeline = [
        {"$match": {"status": "closed", "category": prioritize_category, "created_at": {"$ne": None}, "updated_at": {"$ne": None}}},
        {"$group": {
            "_id": None,
            "avg_hours": {"$avg": {"$divide": [{"$subtract": ["$updated_at", "$created_at"]}, 3600000]}}
        }}
    ]
    res_priority = list(db.issues.aggregate(priority_pipeline))
    current_avg = round(res_priority[0]["avg_hours"] if res_priority and res_priority[0].get("avg_hours") else 24.0, 1)
    
    estimated_priority_avg = round(current_avg * 0.60, 1)
    estimated_improvement = round(current_avg - estimated_priority_avg, 1)
    
    # Other categories resolution times increase by 30%
    other_impacts = []
    other_breach_risk = 0.0
    
    for cat in categories:
        if cat == prioritize_category:
            continue
            
        other_pipeline = [
            {"$match": {"status": "closed", "category": cat, "created_at": {"$ne": None}, "updated_at": {"$ne": None}}},
            {"$group": {
                "_id": None,
                "avg_hours": {"$avg": {"$divide": [{"$subtract": ["$updated_at", "$created_at"]}, 3600000]}}
            }}
        ]
        res_other = list(db.issues.aggregate(other_pipeline))
        cat_avg = round(res_other[0]["avg_hours"] if res_other and res_other[0].get("avg_hours") else 36.0, 1)
        
        est_cat_avg = round(cat_avg * 1.30, 1)
        other_impacts.append({
            "category": cat,
            "current_avg_hours": cat_avg,
            "estimated_avg_hours": est_cat_avg
        })
        
        # Risk increment
        open_count = db.issues.count_documents({"category": cat, "status": {"$nin": ["closed", "rejected"]}})
        other_breach_risk += open_count * 0.15 # 15% of open other issues likely to breach
        
    return {
        "prioritized_category": prioritize_category,
        "estimated_resolution_improvement_hours": estimated_improvement,
        "other_categories_impact": other_impacts,
        "sla_risk_increase": round(min(50.0, other_breach_risk), 1)
    }
