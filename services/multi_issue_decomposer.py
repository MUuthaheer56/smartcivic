"""
SmartCivic v2 — Multi-Issue Decomposition Service
Extracts distinct sub-issues from a multi-issue complaint and routes each sub-issue independently.
"""
import json
import re
from services.ai_service import analyze_text
from services.authority_router import resolve_authority

MAX_SUB_ISSUES = 3

def decompose(text: str, parent_complaint_id: str) -> list:
    """
    Splits multi-issue complaints into individual sub-issue payloads with authority routing.
    Capped at MAX_SUB_ISSUES (3) to prevent abuse and spam amplification.
    """
    if not text:
        return []

    # Simple heuristic splitting on conjunctions
    parts = re.split(r'\band\b|\balso\b|;|\n', text, flags=re.IGNORECASE)
    parts = [p.strip() for p in parts if len(p.strip()) >= 15]

    # Enforce maximum sub-issue cap to prevent spam amplification
    if len(parts) > MAX_SUB_ISSUES:
        parts = parts[:MAX_SUB_ISSUES]

    sub_issues = []
    for idx, part in enumerate(parts):
        analysis = analyze_text(part)
        svc = analysis.get("category", "roads")
        issue_type = analysis.get("type", "general_issue")
        sev = analysis.get("severity", "medium")

        auth = resolve_authority(svc, issue_type)
        sub_issues.append({
            "sub_issue_id": f"{parent_complaint_id}_sub_{idx + 1}",
            "parent_id": str(parent_complaint_id),
            "description": part,
            "service": svc,
            "issue_type": issue_type,
            "severity": sev,
            "authority_primary": auth.get("authority_id"),
            "status": "SUBMITTED"
        })

    return sub_issues
