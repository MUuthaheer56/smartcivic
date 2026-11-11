"""
SmartCivic — Explicit Document Serializers (Plan 3.4 & 3.5)
Implements strict field-whitelisting serializers for public, citizen, and officer access.
Prevents leaking raw internal MongoDB fields (85+ fields, embeddings, citizen_ids, etc.).
"""
from datetime import datetime
from bson import ObjectId
import re


def _format_date(val):
    if isinstance(val, datetime):
        return val.isoformat()
    return str(val) if val else None


def mask_phone_number(phone: str) -> str:
    """Masks phone numbers (e.g. +91 98*** **210) to protect worker and citizen privacy."""
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone)
    if len(digits) >= 10:
        # Keep first 4 and last 3 digits
        prefix = phone[:6]
        suffix = phone[-3:]
        return f"{prefix}*** **{suffix}"
    return "***-***"


def serialize_public_issue(doc: dict) -> dict:
    """
    Public feed serializer: strictly whitelisted fields only.
    Coordinates fuzzed to 3 decimal places (~110m).
    Never includes citizen_id, reporter_id, text_embedding, or private vectors.
    """
    if not doc or not isinstance(doc, dict):
        return {}

    raw_loc = doc.get("location") or {}
    coords = raw_loc.get("coordinates") or [77.595, 12.972]
    fuzzed_coords = [round(float(coords[0]), 3), round(float(coords[1]), 3)]

    # Format images cleanly
    clean_images = []
    for img in doc.get("images", []):
        if isinstance(img, dict):
            clean_images.append({
                "url": img.get("url"),
                "type": img.get("type", "before")
            })
        elif isinstance(img, str):
            clean_images.append({"url": img, "type": "before"})

    return {
        "_id": str(doc.get("_id", "")),
        "id": str(doc.get("issue_id") or doc.get("_id", "")),
        "title": doc.get("title", ""),
        "description": doc.get("description", ""),
        "category": doc.get("category", "other"),
        "type": doc.get("type", "other"),
        "status": doc.get("status", "submitted"),
        "severity": doc.get("severity", "medium"),
        "ward": doc.get("ward", "Ward 1"),
        "ward_id": doc.get("ward_id"),
        "location": {
            "type": "Point",
            "coordinates": fuzzed_coords,
            "fuzzed": True
        },
        "images": clean_images,
        "confirmation_count": int(doc.get("confirmation_count") or doc.get("confirmations") or 0),
        "support_count": int(doc.get("support_count", 0)),
        "is_recurring": bool(doc.get("is_recurring", False)),
        "created_at": _format_date(doc.get("created_at")),
        "updated_at": _format_date(doc.get("updated_at"))
    }


def serialize_citizen_issue(doc: dict, user_id: str = None) -> dict:
    """
    Citizen view serializer: includes own feedback, status, and address.
    For anonymous issues: hides citizen_id completely.
    """
    if not doc or not isinstance(doc, dict):
        return {}

    pub = serialize_public_issue(doc)
    is_anon = bool(doc.get("is_anonymous", False))
    doc_citizen_id = str(doc.get("citizen_id") or "")
    is_owner = bool(user_id and doc_citizen_id == str(user_id) and not is_anon)

    raw_loc = doc.get("location") or {}
    pub["address"] = raw_loc.get("address") or doc.get("address", "")
    pub["is_owner"] = is_owner
    pub["is_anonymous"] = is_anon
    pub["feedback"] = doc.get("feedback")
    pub["verification_status"] = doc.get("verification_status")

    if is_owner and not is_anon:
        pub["citizen_id"] = doc_citizen_id
    else:
        pub.pop("citizen_id", None)

    ai = doc.get("ai_analysis") or {}
    img_dets = ai.get("image_detections") or []
    vis_ev = doc.get("visual_evidence") or ai.get("visual_evidence") or {}
    if not img_dets and vis_ev.get("defect_name"):
        img_dets = [vis_ev["defect_name"]]
    pub["ai_analysis"] = ai
    pub["visual_evidence"] = vis_ev
    pub["image_detections"] = img_dets

    return pub


def serialize_officer_issue(doc: dict) -> dict:
    """
    Officer/Admin view serializer: includes priority, SLA deadline, AI explanation,
    and assigned worker details. Hides identity if is_anonymous is True.
    """
    if not doc or not isinstance(doc, dict):
        return {}

    pub = serialize_public_issue(doc)
    is_anon = bool(doc.get("is_anonymous", False))

    raw_loc = doc.get("location") or {}
    # Officers get precise coordinates if available
    coords = raw_loc.get("coordinates") or [77.5946, 12.9716]
    pub["location"]["coordinates"] = [float(coords[0]), float(coords[1])]
    pub["location"]["fuzzed"] = False
    pub["address"] = raw_loc.get("address") or doc.get("address", "")

    pub["priority"] = doc.get("priority", "P3")
    pub["priority_score"] = doc.get("priority_score", 0)
    pub["priority_decision"] = doc.get("priority_decision", {})
    pub["priority_override"] = doc.get("priority_override", {})
    pub["sla_deadline"] = _format_date(doc.get("sla_deadline"))
    pub["assigned_worker"] = doc.get("assigned_worker") or doc.get("worker_id")
    pub["assigned_worker_id"] = doc.get("assigned_worker_id") or doc.get("worker_id")
    pub["is_anonymous"] = is_anon

    if is_anon:
        pub["citizen_id"] = None
        pub["reporter_name"] = "Anonymous Citizen"
    else:
        pub["citizen_id"] = str(doc.get("citizen_id") or "")
        pub["reporter_name"] = doc.get("reporter_name")

    ai_analysis = doc.get("ai_analysis") or {}
    img_dets = ai_analysis.get("image_detections") or []
    vis_ev = doc.get("visual_evidence") or ai_analysis.get("visual_evidence") or {}
    if not img_dets and vis_ev.get("defect_name"):
        img_dets = [vis_ev["defect_name"]]
    pub["ai_analysis"] = {
        "explanation": ai_analysis.get("explanation"),
        "confidence": ai_analysis.get("confidence", doc.get("ai_confidence")),
        "image_analysis_available": ai_analysis.get("image_analysis_available", False),
        "image_detections": img_dets,
        "category": ai_analysis.get("category"),
        "severity": ai_analysis.get("severity")
    }
    pub["visual_evidence"] = vis_ev
    pub["image_detections"] = img_dets

    return pub
