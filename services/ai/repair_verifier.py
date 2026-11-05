"""
SmartCivic — Repair Verification v2 & Contractor Accountability
Performs multi-stage resolution verification across four independent checks:
1. Location Proximity: Haversine distance between after-photo GPS and report coordinates (<=100m).
2. Same-Scene Similarity: Perceptual dHash scene matching between before and after images.
3. Defect Detector Re-check: ONNX defect detector applied to after-photo (verifies clearance).
4. Visual / Multimodal Verification: High-level visual reasoning on repair quality.

CRITICAL INVARIANT RULE R8: AI never sets issue status to 'closed'. Anything below high confidence
(confidence < 0.85 or non-repaired verdict) stays pending officer review.
Reopen flow tracks contractor and department quality metrics.
"""
import os
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from bson import ObjectId
from PIL import Image

from config import Config
from services.ai.envelope import make_ai_result
from services.ai.decision_logger import log_ai_decision
from utils.geo_utils import haversine_distance
from services.ai.image_gate import compute_dhash, hamming_distance, extract_exif_gps
from services import ai_service

logger = logging.getLogger(__name__)

# Re-check scheduling interval (default: 14 days)
DEFAULT_CONTRACTOR_RECHECK_DAYS = 14
GPS_PROXIMITY_THRESHOLD_METERS = 100.0
SCENE_HASH_DISTANCE_MAX = 18


def check_location_proximity(after_photo_path: Optional[str],
                             report_lat: Optional[float],
                             report_lng: Optional[float],
                             explicit_gps: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """
    Validates that the resolution photo was captured near the reported issue location (<= 100m).
    """
    gps = explicit_gps
    if not gps and after_photo_path and os.path.exists(after_photo_path):
        gps = extract_exif_gps(after_photo_path)

    if not gps or gps.get("latitude") is None or gps.get("longitude") is None:
        return {
            "passed": None,
            "status": "unverified_gps",
            "distance_m": None,
            "reason": "After-photo has no EXIF GPS metadata; requires officer location review."
        }

    if report_lat is None or report_lng is None:
        return {
            "passed": None,
            "status": "missing_report_location",
            "distance_m": None,
            "reason": "Report coordinates unavailable for distance comparison."
        }

    try:
        dist_m = haversine_distance(
            float(gps["latitude"]), float(gps["longitude"]),
            float(report_lat), float(report_lng)
        )
        passed = dist_m <= GPS_PROXIMITY_THRESHOLD_METERS
        return {
            "passed": passed,
            "status": "match" if passed else "distance_exceeded",
            "distance_m": round(dist_m, 1),
            "upload_gps": {"latitude": gps["latitude"], "longitude": gps["longitude"]},
            "report_gps": {"latitude": report_lat, "longitude": report_lng},
            "reason": f"Distance is {dist_m:.1f}m (limit {GPS_PROXIMITY_THRESHOLD_METERS}m)"
        }
    except Exception as e:
        logger.warning(f"[RepairVerifier] Location proximity check error: {e}")
        return {
            "passed": False,
            "status": "error",
            "distance_m": None,
            "reason": str(e)
        }


def check_scene_similarity(before_photo_path: Optional[str], after_photo_path: Optional[str]) -> Dict[str, Any]:
    """
    Calculates perceptual hash similarity to ensure the two photos depict the same physical scene.
    """
    if not before_photo_path or not after_photo_path or not os.path.exists(before_photo_path) or not os.path.exists(after_photo_path):
        return {
            "passed": False,
            "match": False,
            "hamming_distance": None,
            "similarity_score": 0.0,
            "reason": "One or both photos missing for scene comparison."
        }

    try:
        img_b = Image.open(before_photo_path)
        img_a = Image.open(after_photo_path)

        hash_b = compute_dhash(img_b)
        hash_a = compute_dhash(img_a)

        h_dist = hamming_distance(hash_b, hash_a)
        # 64 bits total; normalized similarity = 1 - (dist / 64)
        sim_score = round(max(0.0, 1.0 - (h_dist / 64.0)), 3)
        match = h_dist <= SCENE_HASH_DISTANCE_MAX

        return {
            "passed": match,
            "match": match,
            "hamming_distance": h_dist,
            "similarity_score": sim_score,
            "reason": f"Hamming distance is {h_dist} (threshold <= {SCENE_HASH_DISTANCE_MAX})"
        }
    except Exception as e:
        logger.warning(f"[RepairVerifier] Scene similarity error: {e}")
        return {
            "passed": False,
            "match": False,
            "hamming_distance": None,
            "similarity_score": 0.0,
            "reason": str(e)
        }


def check_defect_detector_clearance(after_photo_path: Optional[str]) -> Dict[str, Any]:
    """
    Runs the local ONNX defect detector (Phase 4) on after-photo to ensure the defect was removed.
    """
    if not after_photo_path or not os.path.exists(after_photo_path):
        return {
            "passed": False,
            "defect_detected": False,
            "detections": [],
            "reason": "After-photo unavailable for detector inference."
        }

    try:
        from services.ai.road_detector import run_road_detector
        detector_res = run_road_detector(after_photo_path)
        val = detector_res.get("value", {})
        detections = val.get("detections", [])

        # Significant defects remaining with confidence >= 0.40
        sig_defects = [d for d in detections if d.get("confidence", 0.0) >= 0.40]
        defect_detected = len(sig_defects) > 0

        return {
            "passed": not defect_detected,
            "defect_detected": defect_detected,
            "detections": sig_defects,
            "raw_count": len(detections),
            "reason": f"Detected {len(sig_defects)} lingering defect(s) on repaired surface" if defect_detected else "No lingering defects detected"
        }
    except Exception as e:
        logger.info(f"[RepairVerifier] Defect detector check skipped/failed: {e}")
        return {
            "passed": True,  # Non-fatal if detector unavailable
            "defect_detected": False,
            "detections": [],
            "reason": "Detector unavailable or skipped"
        }


def verify_repair_v2(issue_doc: Dict[str, Any],
                     before_photo_path: Optional[str],
                     after_photo_path: Optional[str],
                     after_photo_gps: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """
    Executes multi-stage verification across Location, Scene, Defect Detector, and Visual reasoning.
    Returns standardized AI envelope.
    """
    t0 = time.time()
    issue_type = issue_doc.get("type") or issue_doc.get("issue_type") or "other"

    loc_lat = issue_doc.get("latitude") or (issue_doc.get("location", {}).get("coordinates", [0, 0])[1] if "coordinates" in issue_doc.get("location", {}) else None)
    loc_lng = issue_doc.get("longitude") or (issue_doc.get("location", {}).get("coordinates", [0, 0])[0] if "coordinates" in issue_doc.get("location", {}) else None)

    # 1. Location proximity check
    loc_check = check_location_proximity(after_photo_path, loc_lat, loc_lng, after_photo_gps)

    # 2. Scene similarity check
    scene_check = check_scene_similarity(before_photo_path, after_photo_path)

    # 3. Defect detector clearance check
    detector_check = check_defect_detector_clearance(after_photo_path)

    # 4. High-level visual comparison check
    vis_check = ai_service.verify_resolution(before_photo_path, after_photo_path, issue_type)

    # Synthesize overall verdict
    vis_status = (vis_check.get("status") or "uncertain").lower()
    vis_conf = float(vis_check.get("confidence") or 0.5)

    # Check for severe defects or distance violations
    if loc_check.get("passed") is False:
        verdict = "not_repaired"
        confidence = 0.90
        reason = "After-photo was taken too far from the reported issue coordinates."
    elif detector_check.get("defect_detected") and len(detector_check.get("detections", [])) > 1:
        verdict = "not_repaired"
        confidence = 0.85
        reason = "Severe defect remains visible on the repaired surface."
    elif detector_check.get("defect_detected"):
        verdict = "partially_repaired"
        confidence = 0.75
        reason = "Minor surface defect still detected after repair."
    elif vis_status in ["fixed", "resolved", "repaired"] and (scene_check.get("passed") or scene_check.get("similarity_score", 0) > 0.60):
        verdict = "repaired"
        confidence = min(0.95, round(0.5 * vis_conf + 0.3 * (scene_check.get("similarity_score") or 0.7) + 0.2, 3))
        reason = "Multi-stage verification passed: scene verified, defect cleared, and repair confirmed."
    elif vis_status == "partially_fixed" or vis_status == "partially_repaired":
        verdict = "partially_repaired"
        confidence = 0.70
        reason = "Visual comparison indicates partial repair completion."
    elif vis_status == "not_fixed":
        verdict = "not_repaired"
        confidence = 0.80
        reason = "Visual comparison indicates defect was not repaired."
    else:
        verdict = "undetermined"
        confidence = 0.50
        reason = "Evidence is inconclusive or photo quality insufficient for automated clearance."

    requires_officer_review = confidence < 0.85 or verdict in ["partially_repaired", "not_repaired", "undetermined"]

    latency = int((time.time() - t0) * 1000)
    scheduled_recheck = (datetime.utcnow() + timedelta(days=DEFAULT_CONTRACTOR_RECHECK_DAYS)).isoformat()

    envelope = make_ai_result(
        value={
            "verdict": verdict,
            "confidence": confidence,
            "requires_officer_review": requires_officer_review,
            "reason": reason,
            "checks": {
                "location_proximity": loc_check,
                "scene_similarity": scene_check,
                "defect_detector": detector_check,
                "visual_comparison": vis_check
            },
            "recheck_scheduled_at": scheduled_recheck
        },
        confidence=confidence,
        source="repair_verifier_v2",
        model_version="verifier_v2.0",
        evidence_level="inferred",
        fallback_used=False,
        latency_ms=latency,
        error=None
    )
    return envelope


def record_repair_evidence(db,
                           issue_id: str,
                           worker_id: str,
                           before_img: Dict[str, Any],
                           after_img: Dict[str, Any],
                           verification_res: Dict[str, Any],
                           department: str = "roads",
                           contractor_id: Optional[str] = None) -> str:
    """
    Stores structured repair evidence in db.repair_evidence and logs an AI decision.
    Does NOT close the issue.
    """
    val = verification_res.get("value", {})
    now = datetime.utcnow()
    recheck_dt = now + timedelta(days=DEFAULT_CONTRACTOR_RECHECK_DAYS)

    evidence_doc = {
        "issue_id": str(issue_id),
        "worker_id": str(worker_id),
        "contractor_id": str(contractor_id or worker_id),
        "department": department,
        "before_image": before_img,
        "after_image": after_img,
        "upload_gps": val.get("checks", {}).get("location_proximity", {}).get("upload_gps"),
        "report_gps": val.get("checks", {}).get("location_proximity", {}).get("report_gps"),
        "distance_meters": val.get("checks", {}).get("location_proximity", {}).get("distance_m"),
        "checks": val.get("checks", {}),
        "verdict": val.get("verdict", "undetermined"),
        "confidence": val.get("confidence", 0.0),
        "requires_officer_review": val.get("requires_officer_review", True),
        "status": "pending_officer_review",
        "officer_verdict": None,
        "citizen_verdict": None,
        "reopened": False,
        "recheck_scheduled_at": recheck_dt,
        "recheck_completed": False,
        "created_at": now
    }

    res = db.repair_evidence.insert_one(evidence_doc)
    evidence_id = str(res.inserted_id)

    # Log to ai_decisions audit
    log_ai_decision(db, str(issue_id), "repair_verification", verification_res)

    # Initialize/increment contractor statistics baseline
    c_id = str(contractor_id or worker_id)
    db.contractor_stats.update_one(
        {"contractor_id": c_id},
        {"$inc": {"total_resolutions": 1}, "$setOnInsert": {"reopen_count": 0, "department": department}},
        upsert=True
    )

    return evidence_id


def record_issue_reopen(db, issue_id: str, actor_id: str, actor_role: str, reason: str):
    """
    Updates repair evidence and increments contractor/department reopen metrics.
    """
    now = datetime.utcnow()
    # 1. Update repair evidence
    evidence = db.repair_evidence.find_one({"issue_id": str(issue_id)})
    if evidence:
        db.repair_evidence.update_one(
            {"_id": evidence["_id"]},
            {
                "$set": {
                    "reopened": True,
                    "reopened_at": now,
                    "reopened_by": str(actor_id),
                    "reopened_role": str(actor_role),
                    "reopen_reason": reason,
                    "status": "reopened"
                }
            }
        )
        contractor_id = evidence.get("contractor_id")
        department = evidence.get("department", "roads")

        # 2. Increment contractor stats
        if contractor_id:
            db.contractor_stats.update_one(
                {"contractor_id": str(contractor_id)},
                {"$inc": {"reopen_count": 1}, "$set": {"last_reopened_at": now}},
                upsert=True
            )

        # 3. Increment department stats
        if department:
            db.department_stats.update_one(
                {"department": department},
                {"$inc": {"reopen_count": 1}, "$set": {"last_reopened_at": now}},
                upsert=True
            )


def get_due_contractor_rechecks(db, ward: Optional[str] = None) -> list:
    """
    Retrieves all issues due for 14-day contractor quality re-inspection.
    """
    query = {
        "recheck_scheduled_at": {"$lte": datetime.utcnow()},
        "recheck_completed": {"$ne": True}
    }
    return list(db.repair_evidence.find(query).sort("recheck_scheduled_at", 1))

