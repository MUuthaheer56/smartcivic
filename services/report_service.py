"""
SmartCivic+ — Weekly Civic Intelligence Reports Service
Aggregates weekly city stats, caches in database, and builds a professional ReportLab PDF.
"""
from datetime import datetime, timedelta
from io import BytesIO
from bson import ObjectId
from app import db

# ReportLab imports for PDF generation
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

def generate_weekly_report(week_offset: int = 0) -> dict:
    """
    Computes all weekly report metrics from real database records.
    """
    now = datetime.utcnow()
    
    # Calculate start and end dates of the target week (Monday 00:00 to Sunday 23:59)
    # week_offset=0: current week, week_offset=1: last week, etc.
    today = now.date()
    start_of_current_week = today - timedelta(days=today.weekday())
    
    week_start_date = start_of_current_week - timedelta(weeks=week_offset)
    week_end_date = week_start_date + timedelta(days=6)
    
    start_dt = datetime(week_start_date.year, week_start_date.month, week_start_date.day, 0, 0, 0)
    end_dt = datetime(week_end_date.year, week_end_date.month, week_end_date.day, 23, 59, 59)
    
    query = {"created_at": {"$gte": start_dt, "$lte": end_dt}}
    
    total = db.issues.count_documents(query)
    resolved = db.issues.count_documents({"$and": [query, {"status": "closed"}]})
    active = db.issues.count_documents({"$and": [query, {"status": {"$nin": ["closed", "rejected"]}}]})
    critical = db.issues.count_documents({"$and": [query, {"status": {"$nin": ["closed", "rejected"]}, "severity": "critical"}]})
    
    # SLA Compliance
    breached = db.issues.count_documents({"$and": [query, {"sla_status": "breached"}]})
    compliance_pct = 100.0
    if total > 0:
        compliance_pct = round(((total - breached) / total) * 100.0, 1)
        
    # Average resolution hours
    closed_issues = list(db.issues.find({"$and": [query, {"status": "closed", "updated_at": {"$ne": None}}]}))
    avg_hours = 0.0
    if closed_issues:
        total_hours = 0.0
        for issue in closed_issues:
            delta = issue["updated_at"] - issue["created_at"]
            total_hours += delta.total_seconds() / 3600.0
        avg_hours = round(total_hours / len(closed_issues), 1)
        
    # Top categories
    cat_pipeline = [
        {"$match": query},
        {"$group": {"_id": "$category", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 5}
    ]
    top_cats = []
    cat_results = list(db.issues.aggregate(cat_pipeline))
    for r in cat_results:
        pct = round((r["count"] / total) * 100.0, 1) if total > 0 else 0.0
        top_cats.append({"category": r["_id"], "count": r["count"], "pct": pct})
        
    # Top wards by complaints
    ward_pipeline = [
        {"$match": query},
        {"$group": {"_id": "$ward", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 5}
    ]
    top_wards = [{"ward": r["_id"], "count": r["count"]} for r in db.issues.aggregate(ward_pipeline)]
    
    # Top wards by resolution rate
    res_ward_pipeline = [
        {"$match": query},
        {"$group": {
            "_id": "$ward",
            "total": {"$sum": 1},
            "resolved": {"$sum": {"$cond": [{"$eq": ["$status", "closed"]}, 1, 0]}}
        }},
        {"$project": {
            "ward": "$_id",
            "rate": {"$cond": [{"$gt": ["$total", 0]}, {"$multiply": [{"$divide": ["$resolved", "$total"]}, 100.0]}, 0.0]}
        }},
        {"$sort": {"rate": -1}},
        {"$limit": 5}
    ]
    top_res_wards = [{"ward": r["_id"], "rate": round(r["rate"], 1)} for r in db.issues.aggregate(res_ward_pipeline)]
    
    # Worst SLA departments
    sla_pipeline = [
        {"$match": {"$and": [query, {"sla_status": "breached"}]}},
        {"$group": {"_id": "$department", "breach_count": {"$sum": 1}}},
        {"$sort": {"breach_count": -1}},
        {"$limit": 3}
    ]
    worst_sla_depts = [{"department": r["_id"], "breach_count": r["breach_count"]} for r in db.issues.aggregate(sla_pipeline)]
    
    # Emerging hotspots
    hotspots = list(db.hotspots.find({}, limit=5))
    emerging_hotspots = []
    for h in hotspots:
        coords = h.get("location", {}).get("coordinates", [0.0, 0.0])
        emerging_hotspots.append({
            "lat": coords[1],
            "lng": coords[0],
            "category": h.get("category"),
            "ward": h.get("ward"),
            "complaint_count": h.get("complaint_count", 0)
        })
        
    recurring_count = db.issues.count_documents({"$and": [query, {"is_recurring": True}]})
    
    # AI briefing from services.ai_service
    from services.ai_service import generate_officer_briefing
    stats_summary = {
        "emergency_count": critical,
        "sla_breached_count": breached,
        "sla_warning_count": db.issues.count_documents({"$and": [query, {"sla_status": "warning"}]}),
        "available_workers": db.users.count_documents({"role": "worker", "is_available": True}),
        "pending_assignments": db.issues.count_documents({"$and": [query, {"status": "officer_reviewed"}]})
    }
    ai_briefing = generate_officer_briefing(stats_summary)
    
    # Rule-based recommendations
    recommendations = []
    if breached > 3:
        recommendations.append(f"Deploy resources to address the {breached} SLA breaches immediately.")
    if critical > 0:
        recommendations.append(f"Dispatch workers immediately to address {critical} active critical emergencies.")
    for dept_stat in worst_sla_depts:
        recommendations.append(f"Inspect department '{dept_stat['department']}' operations to reduce SLA breach count ({dept_stat['breach_count']}).")
    if not recommendations:
        recommendations.append("All metrics are normal. Continue standard monitoring protocols.")
        
    report_doc = {
        "week_offset": week_offset,
        "week_start": week_start_date.isoformat(),
        "week_end": week_end_date.isoformat(),
        "total_complaints": total,
        "resolved_complaints": resolved,
        "active_complaints": active,
        "critical_complaints": critical,
        "sla_compliance_pct": compliance_pct,
        "avg_resolution_hours": avg_hours,
        "top_categories": top_cats,
        "top_wards_by_complaints": top_wards,
        "top_wards_by_resolution_rate": top_res_wards,
        "worst_sla_departments": worst_sla_depts,
        "emerging_hotspots": emerging_hotspots,
        "recurring_issues_detected": recurring_count,
        "ai_briefing": ai_briefing,
        "recommended_actions": recommendations,
        "generated_at": datetime.utcnow()
    }
    
    return report_doc

def get_or_create_weekly_report(week_offset: int = 0) -> dict:
    """
    Fetches cached report if exists and is fresh (less than 6 hours old). Otherwise regenerates.
    """
    six_hours_ago = datetime.utcnow() - timedelta(hours=6)
    report = db.reports.find_one({"week_offset": week_offset, "generated_at": {"$gte": six_hours_ago}})
    if not report:
        print(f"[Report Service] Regenerating weekly report cache for week_offset={week_offset}...")
        report = generate_weekly_report(week_offset)
        db.reports.delete_many({"week_offset": week_offset})
        db.reports.insert_one(report)
    return report

def trigger_report_generation_job():
    """
    Weekly cron background trigger.
    """
    print("[Report Service] Generating cached weekly report sweep...")
    get_or_create_weekly_report(0)
    get_or_create_weekly_report(1) # cache previous week too

def build_pdf_report(report: dict) -> bytes:
    """
    Creates a professional PDF byte stream of the weekly report using ReportLab.
    """
    buffer = BytesIO()
    
    # Custom styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=24,
        textColor=colors.HexColor('#0f172a'),
        spaceAfter=15
    )
    
    h2_style = ParagraphStyle(
        'SectionHeader',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=14,
        textColor=colors.HexColor('#3b82f6'),
        spaceBefore=15,
        spaceAfter=10
    )
    
    body_style = ParagraphStyle(
        'DocBody',
        parent=styles['BodyText'],
        fontName='Helvetica',
        fontSize=10,
        textColor=colors.HexColor('#334155'),
        spaceAfter=8
    )
    
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    story = []
    
    # Title
    story.append(Paragraph(f"CITY CIVIC INTELLIGENCE REPORT", title_style))
    story.append(Paragraph(f"Reporting Cycle: {report['week_start']} to {report['week_end']}", body_style))
    story.append(Spacer(1, 15))
    
    # Summary Table
    story.append(Paragraph("Key Performance Metrics", h2_style))
    data = [
        ["Metric", "Value"],
        ["Total Complaints Submitted", str(report["total_complaints"])],
        ["Resolved Complaints", str(report["resolved_complaints"])],
        ["Active Unresolved", str(report["active_complaints"])],
        ["Critical Active Emergencies", str(report["critical_complaints"])],
        ["SLA Compliance Rate", f"{report['sla_compliance_pct']}%"],
        ["Average Resolution Time", f"{report['avg_resolution_hours']} hours"]
    ]
    t = Table(data, colWidths=[250, 150])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#0f172a')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
        ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#f8fafc')),
    ]))
    story.append(t)
    story.append(Spacer(1, 15))
    
    # AI Summary
    story.append(Paragraph("AI Executive Briefing Summary", h2_style))
    story.append(Paragraph(report["ai_briefing"], body_style))
    story.append(Spacer(1, 15))
    
    # Recommendations
    story.append(Paragraph("Urgent Recommended Actions", h2_style))
    for act in report["recommended_actions"]:
        story.append(Paragraph(f"• {act}", body_style))
        
    doc.build(story)
    
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
