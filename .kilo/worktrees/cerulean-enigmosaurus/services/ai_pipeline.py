"""
SmartCivic — Single-Pass AI & Intelligence Pipeline Orchestrator
Consolidates language translation, emergency regex safety scans, Gemini text & vision analysis,
safe ONNX check, composite verification, priority rules, authority routing, and impact prediction.
"""
import os
from datetime import datetime
from services import ai_service
from services import ai_classifier
from services import complaint_verifier
from services import authority_router
from services import impact_predictor
from services import yolo_fusion

def _rule_based_fallback_category(description: str) -> str:
    desc = (description or "").lower()
    if "pothole" in desc or "road" in desc:
        return "Roads"
    elif "garbage" in desc or "trash" in desc:
        return "Sanitation"
    elif "light" in desc or "lamp" in desc:
        return "Streetlights"
    elif "water" in desc or "leak" in desc:
        return "Water Supply"
    return "General"

def compute_route_decision(text_analysis: dict, is_emergency: bool, emergency_state: str = None) -> str:
    if emergency_state in ("IMMEDIATE_112", "SAFETY_REVIEW"):
        return emergency_state
    svc = text_analysis.get("category", "other")
    conf = text_analysis.get("confidence", 0.0)
    if svc in ("other", "unknown_other"):
        return "HUMAN_TRIAGE"
    if text_analysis.get("needs_clarification"):
        return "CLARIFICATION_NEEDED"
    if conf >= 0.90:
        return "AUTO_ROUTE"
    if conf >= 0.70:
        return "OFFICER_CONFIRM"
    return "GEMINI_FALLBACK"

def run_unified_ai_pipeline(text: str, location_text: str = "", image_path: str = None, reporter_verified: bool = False, ward_id: str = "ward_1", support_count: int = 0) -> dict:
    """
    Executes the canonical single-pass AI decision pipeline:
    1. Language Detection & Translation
    2. Emergency Regex Safety Scan (pattern_emergency_check)
    3. Gemini / Rule-Based Text Classification
    4. Gemini Vision Analysis & Safe ONNX Model Check
    5. Composite Verification Score (0.0 to 1.0)
    6. Priority Rules Engine (P0 - P3)
    7. Department & Authority Registry Routing
    8. Infrastructure & Monsoon Impact Prediction
    """
    text = (text or "").strip()
    location_text = (location_text or "").strip()
    
    # ── Step 1: Language Detection & Translation ──────────────────────────────
    lang_info = ai_service.detect_and_translate(text)
    translated_text = lang_info.get("translated_text", text)
    
    # ── Step 2: Emergency Regex Safety Scan ─────────────────────────────────
    regex_emergency = (
        ai_classifier.pattern_emergency_check(text) or
        ai_classifier.pattern_emergency_check(translated_text)
    )
    
    # ── Step 3: Text Classification ─────────────────────────────────────────
    text_analysis = ai_service.analyze_complaint_text(translated_text if translated_text else text)
    
    # ── Step 4: Vision Analysis & Safe ONNX Check ──────────────────────────
    image_analysis = None
    yolo_evidence = None
    image_severity_score = 0.0
    
    if image_path and os.path.exists(image_path):
        image_analysis = ai_service.analyze_complaint_image(image_path)
        image_severity_score = float(image_analysis.get("severity_score", 0.0) if isinstance(image_analysis, dict) else 0.0)
        
        # Check ONNX file size (> 1KB) to ensure we never run dummy 28-byte placeholder
        onnx_model_path = os.path.join("ml", "models", "pothole_yolov8n.onnx")
        if os.path.exists(onnx_model_path) and os.path.getsize(onnx_model_path) > 1024:
            try:
                from services import yolo_service
                yolo_res = yolo_service.run_yolo(image_path)
                if yolo_res and yolo_res.get("confidence", 0) >= 0.50:
                    yolo_evidence = yolo_fusion.DEFECT_EVIDENCE_MAP.get(yolo_res.get("defect_class", ""), {})
            except Exception as e:
                print(f"[AI Pipeline] YOLO runner exception: {e}")
                yolo_evidence = None
        else:
            # Explicitly mark visual evidence as None when ONNX is dummy/placeholder
            yolo_evidence = None

    # ── Step 5: Emergency Decision & Safety Override ────────────────────────
    is_emergency = (text_analysis.get("severity") == "critical") or regex_emergency
    emergency_state = None
    if is_emergency:
        if text_analysis.get("confidence", 0.0) >= 0.85 and text_analysis.get("severity") == "critical":
            emergency_state = "IMMEDIATE_112"
        else:
            emergency_state = "SAFETY_REVIEW"
            
    route_decision = compute_route_decision(text_analysis, is_emergency, emergency_state)
    
    # ── Step 6: Composite Verification Score ────────────────────────────────
    confidence_score = complaint_verifier.compute_confidence_score({
        "reporter_verified": reporter_verified,
        "photos": [image_path] if image_path else [],
        "ai_confidence": text_analysis.get("confidence", 0.0),
        "support_count": max(support_count, 0)
    })
    verification_status = complaint_verifier.determine_verification_status(confidence_score, text_analysis)
    
    # ── Step 7: CEFAP Priority & Department Routing ─────────────────────────
    service_type = text_analysis.get("category", "road")
    severity = text_analysis.get("severity", "medium")
    issue_type = text_analysis.get("type", "pothole")
    
    try:
        from app import db
    except Exception:
        db = None
        
    from services.cefap_pipeline import cefap_stage
    
    cefap_result = cefap_stage(db, {
        "issue_id": None,
        "ward_id": ward_id,
        "service": service_type,
        "text_severity": severity,
        "text_confidence": text_analysis.get("confidence", 0.5),
        "image_severity": image_analysis.get("severity") if isinstance(image_analysis, dict) else None,
        "image_confidence": image_analysis.get("confidence") if isinstance(image_analysis, dict) else None,
        "location_type": "unknown",
        "vote_count": max(support_count, 0),
        "historical_complaints": [],
        "created_at": datetime.utcnow(),
        "sla_deadline": None,
    })

    if is_emergency:
        priority = "P0"
    else:
        priority = cefap_result.get("priority", "P2")
        
    authority_info = authority_router.resolve_authority(service_type, issue_type, ward_id)
    
    # ── Step 8: Impact Prediction ───────────────────────────────────────────
    impact_info = impact_predictor.predict_impact({
        "service": service_type,
        "issue_type": issue_type,
        "severity": severity,
        "description": translated_text,
        "location_text": location_text,
        "support_count": support_count
    }, image_severity=image_severity_score)

    return {
        "text_analysis": text_analysis,
        "language": lang_info,
        "image_analysis": image_analysis,
        "visual_evidence": yolo_evidence,
        "emergency": is_emergency,
        "emergency_state": emergency_state,
        "route_decision": route_decision,
        "confidence_score": confidence_score,
        "verification_status": verification_status,
        "priority": priority,
        "cips_score": cefap_result.get("cips"),
        "evidence_reliability": cefap_result.get("evidence_reliability"),
        "evidence_agreement": cefap_result.get("evidence_agreement", 1.0),
        "ctve_triggered": cefap_result.get("ctve_triggered"),
        "ctve_message": cefap_result.get("ctve_message"),
        "verification_required": cefap_result.get("verification_required"),
        "monsoon_active": cefap_result.get("monsoon", {}).get("active", False),
        "cefap": cefap_result,
        "authority": authority_info,
        "impact": impact_info
    }

from concurrent.futures import ThreadPoolExecutor
from bson import ObjectId

_executor = ThreadPoolExecutor(max_workers=4)

def enqueue_ai_analysis(app, issue_id, text: str, location_text: str = "", image_path: str = None, reporter_verified: bool = False, ward_id: str = "ward_1", support_count: int = 0):
    """
    Submits AI pipeline execution to background ThreadPoolExecutor worker.
    Returns immediately so HTTP response is non-blocking.
    """
    _executor.submit(_run_ai_async, app, str(issue_id), text, location_text, image_path, reporter_verified, ward_id, support_count)

def _run_ai_async(app, issue_id_str, text, location_text, image_path, reporter_verified, ward_id, support_count):
    with app.app_context():
        try:
            from app import db, socketio
            ai_res = run_unified_ai_pipeline(
                text=text,
                location_text=location_text,
                image_path=image_path,
                reporter_verified=reporter_verified,
                ward_id=ward_id,
                support_count=support_count
            )
            ai_status = "done"
        except Exception as ex:
            app.logger.warning(f"[Async AI] Exception during AI pipeline for issue {issue_id_str}: {ex}")
            from services.ai_service import rule_based_classify_text
            fallback_text = rule_based_classify_text(text)
            from services.authority_router import resolve_authority
            auth_info = resolve_authority(fallback_text.get("category", "road"), fallback_text.get("type", "pothole"), ward_id)
            ai_res = {
                "text_analysis": fallback_text,
                "priority": "P2" if fallback_text.get("severity") in ("critical", "high") else "P3",
                "authority": auth_info,
                "confidence_score": 0.5,
                "verification_status": "NEEDS_REVIEW"
            }
            ai_status = "fallback"

        try:
            from app import db, socketio
            text_analysis = ai_res.get("text_analysis", {})
            db.issues.update_one(
                {"$or": [{"_id": ObjectId(issue_id_str)}, {"issue_id": issue_id_str}]},
                {"$set": {
                    "ai_analysis": ai_res,
                    "ai_prediction": text_analysis,
                    "ai_status": ai_status,
                    "priority": ai_res.get("priority", "P2"),
                    "cips_score": ai_res.get("cips_score"),
                    "evidence_reliability": ai_res.get("evidence_reliability"),
                    "ctve_triggered": ai_res.get("ctve_triggered", False),
                    "ctve_message": ai_res.get("ctve_message"),
                    "updated_at": datetime.utcnow()
                }}
            )
            if socketio:
                socketio.emit("issue_updated", {"id": issue_id_str, "issue_id": issue_id_str, "ai_status": ai_status}, room=f"ward_{ward_id}")

            try:
                from services.urban_knowledge_graph import analyze_correlations
                res = analyze_correlations(db, ObjectId(issue_id_str))
                if res and res.get("changed"):
                    if socketio:
                        socketio.emit("cluster_updated", {
                            "master_id": str(res["master_id"]),
                            "root_id": str(res["root_id"]),
                            "member_ids": [str(i) for i in res["member_ids"]],
                        })
            except Exception:
                app.logger.exception("Graph correlation analysis failed for issue %s", issue_id_str)
        except Exception as e:
            app.logger.error(f"[Async AI] Error persisting background AI result for issue {issue_id_str}: {e}")

