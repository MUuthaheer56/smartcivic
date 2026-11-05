import os
import io
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from bson import ObjectId
from PIL import Image
import numpy as np

from app import create_app, db
from config import Config
from routes.auth import generate_tokens
from services.ai.repair_verifier import (
    check_location_proximity,
    check_scene_similarity,
    check_defect_detector_clearance,
    verify_repair_v2,
    record_repair_evidence,
    record_issue_reopen,
    get_due_contractor_rechecks,
    GPS_PROXIMITY_THRESHOLD_METERS
)
from services.verification_service import submit_resolution, officer_verify, citizen_verify
from services.complaint_service import create_complaint

@pytest.fixture
def app_instance():
    app = create_app()
    app.config["TESTING"] = True
    return app

@pytest.fixture
def test_client(app_instance):
    return app_instance.test_client()

@pytest.fixture
def sample_images(tmp_path):
    """Creates dummy test images for before and after repair verification."""
    # Before image (dark texture with noise)
    img_b_path = tmp_path / "before.jpg"
    arr_b = np.full((320, 240, 3), 120, dtype=np.uint8)
    arr_b[100:150, 80:160] = 30  # simulated pothole
    Image.fromarray(arr_b).save(str(img_b_path), format="JPEG")

    # After image (repaired texture, same background)
    img_a_path = tmp_path / "after.jpg"
    arr_a = np.full((320, 240, 3), 120, dtype=np.uint8)
    Image.fromarray(arr_a).save(str(img_a_path), format="JPEG")

    # Dissimilar image (unrelated scene)
    img_other_path = tmp_path / "other.jpg"
    arr_other = np.zeros((320, 240, 3), dtype=np.uint8)
    arr_other[::10, ::10] = 255
    Image.fromarray(arr_other).save(str(img_other_path), format="JPEG")

    return {
        "before": str(img_b_path),
        "after": str(img_a_path),
        "other": str(img_other_path)
    }

def test_location_proximity_check():
    """Validates location proximity calculation (<=100m limit)."""
    base_lat, base_lng = 12.9716, 77.5946

    # 1. Nearby (approx 20 meters away)
    near_gps = {"latitude": 12.9717, "longitude": 77.5947}
    res_near = check_location_proximity(None, base_lat, base_lng, near_gps)
    assert res_near["passed"] is True
    assert res_near["distance_m"] < GPS_PROXIMITY_THRESHOLD_METERS

    # 2. Far away (approx 500 meters away)
    far_gps = {"latitude": 12.9760, "longitude": 77.5990}
    res_far = check_location_proximity(None, base_lat, base_lng, far_gps)
    assert res_far["passed"] is False
    assert res_far["distance_m"] > GPS_PROXIMITY_THRESHOLD_METERS

    # 3. Missing GPS metadata
    res_missing = check_location_proximity(None, base_lat, base_lng, None)
    assert res_missing["passed"] is None
    assert res_missing["status"] == "unverified_gps"

def test_scene_similarity_check(sample_images):
    """Validates perceptual dHash scene matching."""
    # Before and after of same location
    res_same = check_scene_similarity(sample_images["before"], sample_images["after"])
    assert res_same["passed"] is True
    assert res_same["similarity_score"] > 0.70

    # Dissimilar scenes
    res_diff = check_scene_similarity(sample_images["before"], sample_images["other"])
    assert res_diff["similarity_score"] < res_same["similarity_score"]

def test_verify_repair_v2_verdicts(sample_images):
    """Tests overall verdict determination and envelope structure."""
    issue_doc = {
        "latitude": 12.9716,
        "longitude": 77.5946,
        "type": "pothole",
        "department": "roads"
    }

    # High-confidence repair
    with patch("services.ai_service.verify_resolution", return_value={"status": "fixed", "confidence": 0.95}):
        env = verify_repair_v2(
            issue_doc=issue_doc,
            before_photo_path=sample_images["before"],
            after_photo_path=sample_images["after"],
            after_photo_gps={"latitude": 12.97165, "longitude": 77.59465}
        )
        assert env["source"] == "repair_verifier_v2"
        assert env["value"]["verdict"] == "repaired"
        assert env["value"]["confidence"] >= 0.85
        assert env["value"]["requires_officer_review"] is False

    # Low-confidence / partial repair requires review
    with patch("services.ai_service.verify_resolution", return_value={"status": "partially_fixed", "confidence": 0.60}):
        env_partial = verify_repair_v2(
            issue_doc=issue_doc,
            before_photo_path=sample_images["before"],
            after_photo_path=sample_images["after"],
            after_photo_gps={"latitude": 12.97165, "longitude": 77.59465}
        )
        assert env_partial["value"]["verdict"] == "partially_repaired"
        assert env_partial["value"]["requires_officer_review"] is True

def test_exit_gate_ai_never_sets_status_to_closed(app_instance, sample_images):
    """
    EXIT GATE INVARIANT: AI cannot set status to 'closed'.
    Submitting resolution with AI_REPAIR_V2_ENABLED must leave status as work_completed,
    never closing the complaint automatically.
    """
    with app_instance.app_context():
        cid = str(ObjectId())
        wid = str(ObjectId())

        issue_doc = create_complaint(
            citizen_id=cid,
            title="Road surface damage",
            description="Deep depression on 1st cross road",
            location={"ward": "Ward 1", "latitude": 12.9716, "longitude": 77.5946},
            category="roads",
            issue_type="pothole"
        )
        issue_id = issue_doc["issue_id"]
        obj_id = issue_doc["_id"]

        # Assign worker and mark work started
        db.issues.update_one(
            {"_id": obj_id},
            {"$set": {"status": "in_progress", "worker_id": wid}}
        )

        before_img = {"filename": "before.jpg", "filepath": sample_images["before"], "url": "/uploads/before.jpg"}
        after_img = {
            "filename": "after.jpg",
            "filepath": sample_images["after"],
            "url": "/uploads/after.jpg",
            "gps": {"latitude": 12.97162, "longitude": 77.59462}
        }

        with patch.object(Config, "AI_REPAIR_V2_ENABLED", True):
            with patch("services.ai_service.verify_resolution", return_value={"status": "fixed", "confidence": 0.99}):
                ai_verif = submit_resolution(
                    issue_id=str(obj_id),
                    worker_id=wid,
                    before_image=before_img,
                    after_image=after_img,
                    notes="Filled pothole with fresh bituminous asphalt mix"
                )

                # Fetch updated issue from DB
                issue_after = db.issues.find_one({"_id": obj_id})
                # MUST NOT BE CLOSED
                assert issue_after["status"] != "closed"
                assert issue_after["status"] == "work_completed"

                # Repair evidence row must exist
                evidence = db.repair_evidence.find_one({"issue_id": str(obj_id)})
                assert evidence is not None
                assert evidence["verdict"] == "repaired"
                assert "recheck_scheduled_at" in evidence

def test_contractor_accountability_and_reopen_flow(app_instance):
    """Verifies reopen flow increments contractor and department stats."""
    with app_instance.app_context():
        contractor_id = str(ObjectId())
        issue_id = str(ObjectId())

        # Simulate initial repair evidence
        db.repair_evidence.insert_one({
            "issue_id": issue_id,
            "contractor_id": contractor_id,
            "department": "roads",
            "recheck_scheduled_at": datetime.utcnow() - timedelta(days=1), # due
            "recheck_completed": False
        })

        # Citizen rejects/reopens
        record_issue_reopen(db, issue_id, "citizen_123", "citizen", "Pothole sunken in after rain")

        # Verify contractor stats incremented
        c_stats = db.contractor_stats.find_one({"contractor_id": contractor_id})
        assert c_stats is not None
        assert c_stats["reopen_count"] >= 1

        # Verify department stats incremented
        d_stats = db.department_stats.find_one({"department": "roads"})
        assert d_stats is not None
        assert d_stats["reopen_count"] >= 1

        # Verify scheduled re-checks query
        due = get_due_contractor_rechecks(db)
        assert len(due) >= 1

def test_privacy_repair_evidence_endpoint_rbac(app_instance, test_client):
    """
    Section 4.2 Privacy: repair_evidence is restricted to officer/admin roles,
    kept out of public / citizen API responses.
    """
    with app_instance.app_context():
        issue_id = str(ObjectId())
        db.repair_evidence.insert_one({
            "issue_id": issue_id,
            "verdict": "repaired",
            "confidence": 0.95
        })

        # 1. Unauthenticated request -> 401
        res_anon = test_client.get(f"/api/issues/{issue_id}/repair-evidence")
        assert res_anon.status_code == 401

        # 2. Citizen request -> 403 Forbidden
        cid = str(ObjectId())
        db.users.update_one({"_id": ObjectId(cid)}, {"$set": {"email": f"c_{cid}@t.com", "role": "citizen"}}, upsert=True)
        c_token, _ = generate_tokens(cid, "citizen", "Ward 1")
        res_cit = test_client.get(f"/api/issues/{issue_id}/repair-evidence", headers={"Authorization": f"Bearer {c_token}"})
        assert res_cit.status_code == 403

        # 3. Officer request -> 200 OK
        oid = str(ObjectId())
        db.users.update_one({"_id": ObjectId(oid)}, {"$set": {"email": f"o_{oid}@t.com", "role": "officer"}}, upsert=True)
        o_token, _ = generate_tokens(oid, "officer", "all")
        res_off = test_client.get(f"/api/issues/{issue_id}/repair-evidence", headers={"Authorization": f"Bearer {o_token}"})
        assert res_off.status_code == 200
        data = res_off.get_json()
        assert len(data["evidence"]) >= 1

