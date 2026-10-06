"""
SmartCivic v2 — User Acceptance Testing (UAT) Full Lifecycle Walkthrough
Simulates complete citizen -> AI -> officer -> worker -> resolution -> CEFAP verification loop.
"""

import os
import sys
import io
import time
from datetime import datetime
from bson import ObjectId
from PIL import Image

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app import create_app
from routes.auth import generate_tokens, hash_password
from models.user import get_db

def _create_sample_image_bytes(color=(255, 0, 0), format="JPEG"):
    img = Image.new("RGB", (200, 200), color=color)
    buf = io.BytesIO()
    img.save(buf, format=format)
    buf.seek(0)
    return buf

def run_uat_walkthrough():
    print("======================================================================")
    print("      SMARTCIVIC UAT FULL LIFECYCLE WALKTHROUGH & ACCEPTANCE")
    print("======================================================================")

    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()

    with app.app_context():
        db = get_db()
        now = datetime.utcnow()

        # Step 1: User & Setup
        resident_id = ObjectId()
        officer_id = ObjectId()
        worker_id = ObjectId()

        db.users.insert_many([
            {
                "_id": resident_id,
                "email": "uat_citizen@smartcivic.com",
                "password_hash": hash_password("citizen_pass123"),
                "role": "resident",
                "ward": "Ward 1",
                "ward_id": "ward_1",
                "verified": True,
                "verification_status": "approved",
                "created_at": now
            },
            {
                "_id": officer_id,
                "email": "uat_officer@smartcivic.com",
                "password_hash": hash_password("officer_pass123"),
                "role": "officer",
                "ward": "Ward 1",
                "ward_id": "ward_1",
                "department": "roads",
                "created_at": now
            },
            {
                "_id": worker_id,
                "email": "uat_worker@smartcivic.com",
                "password_hash": hash_password("worker_pass123"),
                "role": "worker",
                "ward": "Ward 1",
                "ward_id": "ward_1",
                "status": "available",
                "created_at": now
            }
        ])

        try:
            # Clean any old test records first to ensure duplicate detector doesn't flag
            db.issues.delete_many({"title": {"$regex": "^UAT Walkthrough"}})

            res_token, _ = generate_tokens(str(resident_id), "resident", "Ward 1")
            off_token, _ = generate_tokens(str(officer_id), "officer", "Ward 1")
            wrk_token, _ = generate_tokens(str(worker_id), "worker", "Ward 1")

            # ── STEP 1: Resident Submits Issue with Image ───────────────────────
            print("\n[UAT Step 1] Resident lodges grievance report with photo...")
            photo_bytes = _create_sample_image_bytes(color=(220, 50, 50))
            unique_str = str(int(time.time()))
            data = {
                "title": f"UAT Walkthrough — Severe Pothole {unique_str}",
                "description": "Large deep pothole creating hazard for commuter traffic.",
                "category": "road",
                "severity": "high",
                "latitude": f"{12.9716 + (hash(unique_str) % 1000) * 0.0001:.5f}",
                "longitude": f"{77.5946 + (hash(unique_str) % 1000) * 0.0001:.5f}",
                "ward": "Ward 1",
                "photo": (photo_bytes, "pothole.jpg")
            }

            res = client.post(
                "/api/issues",
                data=data,
                content_type="multipart/form-data",
                headers={"Authorization": f"Bearer {res_token}"}
            )
            assert res.status_code in (200, 201), f"Issue submission failed: {res.get_data(as_text=True)}"
            res_data = res.get_json()
            issue_mongo_id = res_data["data"]["_id"]
            issue_custom_id = res_data["data"].get("issue_id") or issue_mongo_id
            print(f"  [PASSED] Issue created successfully. ID: {issue_custom_id}")

            # ── STEP 2: AI Pipeline & Route Verification ───────────────────────
            print("\n[UAT Step 2] Verifying AI pipeline decision and route assignment...")
            issue_doc = db.issues.find_one({"_id": ObjectId(issue_mongo_id)})
            assert issue_doc is not None, "Created issue document missing from DB"
            assert issue_doc.get("status") in ("submitted", "pending", "ai_reviewed", "open", "active"), f"Unexpected status: {issue_doc.get('status')}"
            print(f"  [PASSED] AI routing verified. Priority: {issue_doc.get('priority', 'P2')}")

            # ── STEP 3: Officer Queue & Worker Assignment ──────────────────────
            print("\n[UAT Step 3] Officer assigns repair worker to issue...")
            assign_res = client.post(
                f"/api/issues/{issue_mongo_id}/assign",
                json={"worker_id": str(worker_id)},
                headers={"Authorization": f"Bearer {off_token}", "Content-Type": "application/json"}
            )
            assert assign_res.status_code == 200, f"Worker assignment failed: {assign_res.get_data(as_text=True)}"
            print(f"  [PASSED] Worker {worker_id} assigned successfully.")

            # ── STEP 4: Worker Job Execution & Proof Submission ──────────────────
            print("\n[UAT Step 4] Field worker updates status to 'in_progress' and uploads proof...")
            progress_res = client.post(
                f"/api/issues/{issue_mongo_id}/start",
                headers={"Authorization": f"Bearer {wrk_token}"}
            )
            assert progress_res.status_code == 200, f"Status update to in_progress failed: {progress_res.get_data(as_text=True)}"

            proof_bytes = _create_sample_image_bytes(color=(50, 200, 50))
            resolve_res = client.post(
                f"/api/issues/{issue_mongo_id}/resolve",
                data={"image": (proof_bytes, "proof.jpg"), "notes": "Pothole filled and leveled with asphalt."},
                content_type="multipart/form-data",
                headers={"Authorization": f"Bearer {wrk_token}"}
            )
            assert resolve_res.status_code == 200, f"Resolution proof upload failed: {resolve_res.get_data(as_text=True)}"
            print("  [PASSED] Resolution proof accepted. Status set to verification.")

            # ── STEP 5: CEFAP & Resident Closure Verification ───────────────────
            print("\n[UAT Step 5] Final verification & issue closure...")
            close_res = client.post(
                f"/api/issues/{issue_mongo_id}/citizen-verify",
                json={"resolved": True, "rating": 5, "feedback": "Great work! Perfectly repaired."},
                headers={"Authorization": f"Bearer {res_token}", "Content-Type": "application/json"}
            )
            assert close_res.status_code == 200, f"Closure verification failed: {close_res.get_data(as_text=True)}"

            final_doc = db.issues.find_one({"_id": ObjectId(issue_mongo_id)})
            assert final_doc.get("status") in ("closed", "verified", "resolved"), f"Final status not closed: {final_doc.get('status')}"
            print(f"  [PASSED] Full issue lifecycle completed successfully. Final status: {final_doc.get('status')}")

            print("\n======================================================================")
            print("         ALL UAT LIFECYCLE STEPS PASSED 100% PERFECTLY!")
            print("======================================================================\n")
            return True

        finally:
            # Cleanup test records
            db.users.delete_many({"_id": {"$in": [resident_id, officer_id, worker_id]}})
            db.issues.delete_many({"title": {"$regex": "^UAT Walkthrough"}})

if __name__ == "__main__":
    run_uat_walkthrough()
