"""
SmartCivic+ — Analytics API Blueprint
Provides real aggregate city-wide database statistics.
"""
from flask import Blueprint, jsonify, g, request
from datetime import datetime
from app import db
from routes.auth import require_auth, require_role
from services import sla_service

analytics_api_bp = Blueprint('analytics_api', __name__)

@analytics_api_bp.route('/api/analytics/overview', methods=['GET'])
@require_auth
@require_role('officer')
def get_overview_analytics():
    query = {}
    officer_ward = g.current_user.get("ward")
    if officer_ward != "all":
        query["ward"] = officer_ward
        
    total_complaints = db.issues.count_documents(query)
    resolved = db.issues.count_documents({**query, "status": "closed"})
    pending = db.issues.count_documents({**query, "status": {"$nin": ["closed", "rejected"]}})
    critical = db.issues.count_documents({**query, "status": {"$nin": ["closed", "rejected"]}, "severity": "critical"})
    
    # SLA health breakdown
    sla_health = sla_service.get_sla_health(ward=None if officer_ward == "all" else officer_ward)
    
    return jsonify({
        "success": True,
        "data": {
            "total": total_complaints,
            "resolved": resolved,
            "pending": pending,
            "critical_active": critical,
            "sla": sla_health
        }
    }), 200

@analytics_api_bp.route('/api/analytics/by-ward', methods=['GET'])
@require_auth
@require_role('officer')
def get_by_ward_analytics():
    # MongoDB aggregation
    pipeline = [
        {"$group": {"_id": "$ward", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}}
    ]
    
    # Officer ward constraint
    officer_ward = g.current_user.get("ward")
    if officer_ward != "all":
        pipeline.insert(0, {"$match": {"ward": officer_ward}})
        
    results = list(db.issues.aggregate(pipeline))
    
    from services.briefing_service import calculate_ward_health_score
    data = []
    for r in results:
        w_name = r["_id"]
        if not w_name:
            continue
        score_doc = db.ward_scores.find_one({"ward": w_name})
        if score_doc:
            score = score_doc.get("score", 100)
        else:
            try:
                score = calculate_ward_health_score(w_name)
            except Exception:
                score = 100
        data.append({
            "ward": w_name,
            "count": r["count"],
            "ward_health_score": score
        })
    
    return jsonify({"success": True, "data": data}), 200

@analytics_api_bp.route('/api/analytics/by-department', methods=['GET'])
@require_auth
@require_role('officer')
def get_by_department_analytics():
    pipeline = [
        {
            "$group": {
                "_id": "$department",
                "count": {"$sum": 1},
                "average_rating": {"$avg": "$citizen_rating"}
            }
        },
        {"$sort": {"count": -1}}
    ]
    
    # Officer ward constraint
    officer_ward = g.current_user.get("ward")
    if officer_ward != "all":
        pipeline.insert(0, {"$match": {"ward": officer_ward}})
        
    results = list(db.issues.aggregate(pipeline))
    data = [
        {
            "department": r["_id"],
            "count": r["count"],
            "average_rating": round(r["average_rating"], 2) if r.get("average_rating") is not None else 0.0
        } for r in results
    ]
    
    return jsonify({"success": True, "data": data}), 200

@analytics_api_bp.route('/api/analytics/sla', methods=['GET'])
@require_auth
@require_role('officer')
def get_sla_analytics():
    officer_ward = g.current_user.get("ward")
    ward = None if officer_ward == "all" else officer_ward
    health = sla_service.get_sla_health(ward=ward)
    return jsonify({"success": True, "data": health}), 200

@analytics_api_bp.route('/api/officer/briefing', methods=['GET'])
@require_auth
@require_role('officer')
def get_officer_briefing():
    from services.briefing_service import get_cached_briefing, regenerate_briefing
    
    # Query param ?refresh=true forces regeneration
    refresh = request.args.get("refresh", "false").lower() == "true"
    if refresh:
        briefing = regenerate_briefing()
    else:
        briefing = get_cached_briefing()
        
    return jsonify({
        "success": True,
        "data": {
            "briefing_text": briefing.get("briefing_text"),
            "generated_at": briefing.get("generated_at").isoformat() if briefing.get("generated_at") else None,
            "stats": briefing.get("stats"),
            "recommended_actions": briefing.get("recommended_actions", [])
        }
    }), 200

@analytics_api_bp.route('/api/public/stats', methods=['GET'])
def get_public_stats():
    total = db.issues.count_documents({})
    resolved = db.issues.count_documents({"status": "closed"})
    active = db.issues.count_documents({"status": {"$nin": ["closed", "rejected"]}})
    critical = db.issues.count_documents({"status": {"$nin": ["closed", "rejected"]}, "severity": "critical"})
    
    # SLA Compliance rate
    breached = db.issues.count_documents({"sla_status": "breached"})
    compliance_pct = 100.0
    if total > 0:
        compliance_pct = round(((total - breached) / total) * 100.0, 1)
        
    # Average resolution time in hours
    closed_issues = list(db.issues.find({"status": "closed", "created_at": {"$ne": None}, "updated_at": {"$ne": None}}))
    avg_hours = 0.0
    if closed_issues:
        total_hours = 0.0
        for issue in closed_issues:
            delta = issue["updated_at"] - issue["created_at"]
            total_hours += delta.total_seconds() / 3600.0
        avg_hours = round(total_hours / len(closed_issues), 1)
        
    # Complaints this month
    now = datetime.utcnow()
    start_of_month = datetime(now.year, now.month, 1)
    month_count = db.issues.count_documents({"created_at": {"$gte": start_of_month}})
    
    # Top 5 categories
    cat_pipeline = [
        {"$group": {"_id": "$category", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 5}
    ]
    top_cats = [{"category": r["_id"], "count": r["count"]} for r in db.issues.aggregate(cat_pipeline)]
    
    # Top 5 wards by issues
    ward_pipeline = [
        {"$group": {"_id": "$ward", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 5}
    ]
    top_wards = [{"ward": r["_id"], "count": r["count"]} for r in db.issues.aggregate(ward_pipeline)]
    
    return jsonify({
        "success": True,
        "data": {
            "total_complaints": total,
            "resolved_complaints": resolved,
            "active_complaints": active,
            "critical_active": critical,
            "avg_resolution_hours": avg_hours,
            "sla_compliance_pct": compliance_pct,
            "complaints_this_month": month_count,
            "top_categories": top_cats,
            "top_wards_by_issues": top_wards,
            "last_updated": now.isoformat()
        }
    }), 200

@analytics_api_bp.route('/api/analytics/recurring', methods=['GET'])
@require_auth
@require_role('officer')
def list_recurring_hotspots():
    query = {"is_recurring": True}
    officer_ward = g.current_user.get("ward")
    if officer_ward != "all":
        query["ward"] = officer_ward
        
    hotspots = list(db.issues.find(query, {
        "location": 1,
        "category": 1,
        "ward": 1,
        "recurrence_count": 1,
        "first_occurrence_at": 1,
        "created_at": 1
    }).sort("recurrence_count", -1))
    
    from utils import serialize
    data = []
    for h in hotspots:
        data.append({
            "location": h.get("location"),
            "category": h.get("category"),
            "ward": h.get("ward"),
            "total_occurrences": h.get("recurrence_count", 0),
            "first_occurrence": h.get("first_occurrence_at").isoformat() if h.get("first_occurrence_at") else None,
            "last_occurrence": h.get("created_at").isoformat() if h.get("created_at") else None,
            "current_issue_id": str(h.get("_id"))
        })
        
    return jsonify({"success": True, "data": serialize(data)}), 200

@analytics_api_bp.route('/api/analytics/ai-performance', methods=['GET'])
@require_auth
@require_role('officer')
def get_ai_performance():
    from services.ai_evaluation_service import get_accuracy_stats
    days = int(request.args.get("days", 30))
    task = request.args.get("task")
    stats = get_accuracy_stats(ai_task=task, days=days)
    return jsonify({"success": True, "data": stats}), 200

@analytics_api_bp.route('/api/analytics/ai-calibration', methods=['GET'])
@require_auth
@require_role('officer')
def get_ai_calibration():
    from services.ai_evaluation_service import get_confidence_calibration
    task = request.args.get("task", "classification")
    calibration = get_confidence_calibration(ai_task=task)
    return jsonify({"success": True, "data": calibration}), 200

@analytics_api_bp.route('/api/analytics/infrastructure', methods=['GET'])
@require_auth
@require_role('officer')
def get_infrastructure_analytics():
    from services.infrastructure_service import get_infrastructure_health_overview
    
    ward = request.args.get("ward")
    seg_type = request.args.get("type")
    min_score = int(request.args.get("min_score", 0))
    max_score = int(request.args.get("max_score", 100))
    
    # Filter by user ward if they are restricted
    officer_ward = g.current_user.get("ward")
    if officer_ward != "all":
        ward = officer_ward
        
    results = get_infrastructure_health_overview(
        ward=ward,
        segment_type=seg_type,
        min_score=min_score,
        max_score=max_score
    )
    from utils import serialize
    return jsonify({"success": True, "data": serialize(results)}), 200

@analytics_api_bp.route('/api/analytics/simulate/worker-addition', methods=['POST'])
@require_auth
@require_role('officer')
def post_simulate_worker_addition():
    from services.simulation_service import simulate_worker_addition
    data = request.get_json() or {}
    ward = data.get("ward")
    dept = data.get("department", "roads")
    add_count = int(data.get("additional_workers", 1))
    
    # Restrict ward simulation if officer is restricted
    officer_ward = g.current_user.get("ward")
    if officer_ward != "all":
        ward = officer_ward
        
    result = simulate_worker_addition(ward, dept, add_count)
    return jsonify({"success": True, "data": result}), 200

@analytics_api_bp.route('/api/analytics/simulate/priority-shift', methods=['POST'])
@require_auth
@require_role('officer')
def post_simulate_priority_shift():
    from services.simulation_service import simulate_category_priority_shift
    data = request.get_json() or {}
    cat = data.get("prioritize_category", "road")
    
    result = simulate_category_priority_shift(cat)
    return jsonify({"success": True, "data": result}), 200

@analytics_api_bp.route('/api/analytics/weekly-report', methods=['GET'])
@require_auth
@require_role('officer')
def get_weekly_report():
    from services.report_service import get_or_create_weekly_report
    week_offset = int(request.args.get("week_offset", 0))
    report = get_or_create_weekly_report(week_offset)
    from utils import serialize
    return jsonify({"success": True, "data": serialize(report)}), 200

@analytics_api_bp.route('/api/analytics/weekly-report/pdf', methods=['GET'])
@require_auth
@require_role('officer')
def get_weekly_report_pdf():
    from services.report_service import get_or_create_weekly_report, build_pdf_report
    from flask import send_file
    from io import BytesIO
    
    week_offset = int(request.args.get("week_offset", 0))
    report = get_or_create_weekly_report(week_offset)
    pdf_data = build_pdf_report(report)
    
    return send_file(
        BytesIO(pdf_data),
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f"smartcivic_report_week_{week_offset}.pdf"
    )

@analytics_api_bp.route('/api/admin/health', methods=['GET'])
@require_auth
@require_role('officer')
def get_admin_health():
    from services.health_service import get_system_health
    health = get_system_health()
    
    recent_errors = []
    logs = list(db.audit_logs.find({"action": "ERROR"}).sort("timestamp", -1).limit(5))
    from utils import serialize
    for log in logs:
        recent_errors.append({
            "timestamp": log["timestamp"].isoformat() if log.get("timestamp") else None,
            "message": log.get("reason"),
            "context": log.get("details", {})
        })
    health["recent_errors"] = serialize(recent_errors)
    
    return jsonify({"success": True, "data": health}), 200

from app import limiter

@analytics_api_bp.route('/api/analytics/ask', methods=['POST'])
@require_auth
@require_role('officer')
@limiter.limit("20 per hour")
def post_analytics_ask():
    from services.ai_service import parse_search_query, answer_analytics_question
    data = request.get_json() or {}
    question = data.get("question", "")
    
    # 1. Parse question to identify entities
    filters = parse_search_query(question)
    
    # 2. Build DB query based on parsed filters
    query = {}
    
    # Restrict ward if officer is restricted
    officer_ward = g.current_user.get("ward")
    if officer_ward != "all":
        query["ward"] = officer_ward
    elif "ward" in filters:
        query["ward"] = filters["ward"]
        
    if "category" in filters:
        query["category"] = filters["category"]
    if "status" in filters:
        query["status"] = filters["status"]
    if "severity" in filters:
        query["severity"] = filters["severity"]
        
    # Get matches
    total_matches = db.issues.count_documents(query)
    
    # Gather other aggregate context metrics
    context_stats = {
        "ward": query.get("ward", "all"),
        "category": query.get("category", "all"),
        "status": query.get("status", "all"),
        "total_issues_matched": total_matches
    }
    
    # 3. Call answer_analytics_question
    answer = answer_analytics_question(question, context_stats)
    
    return jsonify({
        "success": True,
        "answer": answer,
        "question": question,
        "stats_used": context_stats,
        "generated_at": datetime.utcnow().isoformat()
    }), 200
