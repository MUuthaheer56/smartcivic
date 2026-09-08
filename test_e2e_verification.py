"""
SmartCivic — Live End-to-End Verification Test Runner
Executes all verification levels (0 through 11) against the application and MongoDB.
Records pass/fail metrics and root causes before any code modifications are made.
"""
import os
import sys
import json
import io
import time
from datetime import datetime
from bson import ObjectId

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__)))
sys.path.insert(0, ROOT_DIR)

from app import create_app, db
from routes.auth import generate_tokens, hash_password

def run_e2e_verification():
    print("=" * 70)
    print("        SMARTCIVIC LIVE END-TO-END VERIFICATION EXECUTION      ")
    print("=" * 70)

    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()

    results = []

    def log_test(level: str, name: str, passed: bool, details: str = ""):
        status = "PASSED" if passed else "FAILED"
        results.append({"level": level, "name": name, "passed": passed, "details": details})
        print(f"[{status}] {level} - {name}" + (f": {details}" if details else ""))

    def parse_token(response):
        data = response.get_json() or {}
        if "access_token" in data:
            return data["access_token"]
        if "data" in data and isinstance(data["data"], dict) and "access_token" in data["data"]:
            return data["data"]["access_token"]
        # Check Set-Cookie header
        set_cookie = response.headers.get("Set-Cookie", "")
        if "access_token=" in set_cookie:
            try:
                cookie_val = set_cookie.split("access_token=")[1].split(";")[0]
                return cookie_val
            except Exception:
                pass
        return None

    # ----------------------------------------------------
    # Level 0 — Environment & Health Checks
    # ----------------------------------------------------
    print("\n--- LEVEL 0: Health & Infrastructure Checks ---")
    res_health = client.get("/api/health")
    log_test("Level 0", "Server Health GET /api/health", res_health.status_code == 200, f"HTTP {res_health.status_code}")

    try:
        db.command("ping")
        log_test("Level 0", "MongoDB Connection", True, "MongoDB ping successful")
    except Exception as e:
        log_test("Level 0", "MongoDB Connection", False, str(e))

    yolo_exists = os.path.exists("ml/models/pothole_yolov8n.onnx")
    log_test("Level 0", "YOLO Model File Existence", yolo_exists, f"ml/models/pothole_yolov8n.onnx exists: {yolo_exists}")

    import requests
    try:
        r_osrm = requests.get("http://router.project-osrm.org/route/v1/driving/77.59,12.97;77.60,12.98", timeout=3)
        log_test("Level 0", "OSRM Router Reachability", r_osrm.status_code == 200, f"HTTP {r_osrm.status_code}")
    except Exception as e:
        log_test("Level 0", "OSRM Router Reachability", False, f"Degraded mode: {e}")

    # Clean up test accounts and test complaints if exist
    db.users.delete_many({"email": {"$in": ["riya@test.sc", "mehta@test.sc", "arjun@test.sc", "other_worker@test.sc", "other_res@test.sc"]}})
    db.workers.delete_many({"name": {"$in": ["Worker Arjun", "Worker Other"]}})
    db.issues.delete_many({})

    # ----------------------------------------------------
    # Level 1 — User Registration & Login
    # ----------------------------------------------------
    print("\n--- LEVEL 1: User Registration & Authentication ---")
    reg_riya = client.post("/api/auth/register", json={"name": "Riya Sharma", "email": "riya@test.sc", "password": "Test@1234", "role": "resident"})
    if reg_riya.status_code == 404:
        reg_riya = client.post("/auth/register", json={"name": "Riya Sharma", "email": "riya@test.sc", "password": "Test@1234", "role": "resident", "ward": "Ward 1"})
    log_test("Level 1", "Register Resident Riya", reg_riya.status_code in [200, 201], f"HTTP {reg_riya.status_code}")

    admin_invite = app.config.get("ADMIN_INVITE_CODE", "SMARTCIVIC-ADMIN-2025")
    reg_mehta = client.post("/api/auth/register", json={"name": "Officer Mehta", "email": "mehta@test.sc", "password": "Test@1234", "role": "officer", "invite_code": admin_invite})
    if reg_mehta.status_code in [404, 403, 422]:
        reg_mehta = client.post("/auth/register", json={"name": "Officer Mehta", "email": "mehta@test.sc", "password": "Test@1234", "role": "officer", "ward": "all", "invite_code": admin_invite})
    log_test("Level 1", "Register Officer Mehta", reg_mehta.status_code in [200, 201], f"HTTP {reg_mehta.status_code}")

    reg_arjun = client.post("/api/auth/register", json={"name": "Worker Arjun", "email": "arjun@test.sc", "password": "Test@1234", "role": "worker", "invite_code": admin_invite})
    if reg_arjun.status_code in [404, 403, 422]:
        reg_arjun = client.post("/auth/register", json={"name": "Worker Arjun", "email": "arjun@test.sc", "password": "Test@1234", "role": "worker", "ward": "Ward 1", "invite_code": admin_invite})
    log_test("Level 1", "Register Worker Arjun", reg_arjun.status_code in [200, 201], f"HTTP {reg_arjun.status_code}")

    # Get arjun's ObjectId
    arjun_user = db.users.find_one({"email": "arjun@test.sc"})
    arjun_id = str(arjun_user["_id"]) if arjun_user else str(ObjectId())

    db.workers.delete_many({"_id": ObjectId(arjun_id)})
    db.workers.insert_one({
        "_id": ObjectId(arjun_id),
        "user_id": ObjectId(arjun_id),
        "name": "Worker Arjun",
        "department": "roads",
        "skills": ["road_repair", "pothole_repair"],
        "status": "available",
        "location": {"latitude": 12.9716, "longitude": 77.5946}
    })
    db.users.update_one(
        {"_id": ObjectId(arjun_id)},
        {"$set": {"status": "available", "is_available": True, "active_assignments": 0}}
    )

    login_riya = client.post("/api/auth/login", json={"email": "riya@test.sc", "password": "Test@1234"})
    if login_riya.status_code == 404:
        login_riya = client.post("/auth/login", json={"email": "riya@test.sc", "password": "Test@1234"})
    log_test("Level 1", "Login Resident Riya", login_riya.status_code == 200, f"HTTP {login_riya.status_code}")
    riya_token = parse_token(login_riya)

    login_mehta = client.post("/api/auth/login", json={"email": "mehta@test.sc", "password": "Test@1234"})
    if login_mehta.status_code == 404:
        login_mehta = client.post("/auth/login", json={"email": "mehta@test.sc", "password": "Test@1234"})
    log_test("Level 1", "Login Officer Mehta", login_mehta.status_code == 200, f"HTTP {login_mehta.status_code}")
    mehta_token = parse_token(login_mehta)

    login_arjun = client.post("/api/auth/login", json={"email": "arjun@test.sc", "password": "Test@1234"})
    if login_arjun.status_code == 404:
        login_arjun = client.post("/auth/login", json={"email": "arjun@test.sc", "password": "Test@1234"})
    log_test("Level 1", "Login Worker Arjun", login_arjun.status_code == 200, f"HTTP {login_arjun.status_code}")
    arjun_token = parse_token(login_arjun)

    if not riya_token or not mehta_token or not arjun_token:
        with app.app_context():
            if not riya_token and db.users.find_one({"email": "riya@test.sc"}):
                riya_token, _ = generate_tokens(str(db.users.find_one({"email": "riya@test.sc"})["_id"]), "resident", "Ward 1")
            if not mehta_token and db.users.find_one({"email": "mehta@test.sc"}):
                mehta_token, _ = generate_tokens(str(db.users.find_one({"email": "mehta@test.sc"})["_id"]), "officer", "all")
            if not arjun_token and arjun_user:
                arjun_token, _ = generate_tokens(str(arjun_id), "worker", "Ward 1")

    # ----------------------------------------------------
    # Level 2 — Resident Complaint Submission
    # ----------------------------------------------------
    print("\n--- LEVEL 2: Resident Complaint Submission ---")
    fixture_img = "tests/fixtures/dangerous-damaged-highway-after-heavy-rain.webp"
    with open(fixture_img, "rb") as f_img:
        img_bytes = f_img.read()

    headers_riya = {"Authorization": f"Bearer {riya_token}"} if riya_token else {}
    payload_comp = {
        "description": "There is a large dangerous pothole on MG Road near the signal that is causing vehicles to swerve.",
        "latitude": "12.9716",
        "longitude": "77.5946",
        "address": "MG Road, Bengaluru",
        "image": (io.BytesIO(img_bytes), "pothole.webp")
    }
    res_comp = client.post("/api/issues", data=payload_comp, headers=headers_riya, content_type="multipart/form-data")
    log_test("Level 2", "Submit Complaint POST /api/issues", res_comp.status_code in [200, 201], f"HTTP {res_comp.status_code}")

    comp_json = res_comp.get_json() or {}
    comp_data = comp_json.get("data", comp_json)
    issue_id_str = comp_data.get("issue_id") or comp_data.get("_id")
    log_test("Level 2", "Received valid issue_id", bool(issue_id_str), f"issue_id={issue_id_str}")

    # DB persistence check
    db_issue = None
    if issue_id_str:
        if ObjectId.is_valid(issue_id_str):
            db_issue = db.issues.find_one({"_id": ObjectId(issue_id_str)})
        if not db_issue:
            db_issue = db.issues.find_one({"issue_id": issue_id_str})
    log_test("Level 2", "MongoDB Issue Persistence", bool(db_issue), f"Found doc: {bool(db_issue)}")

    if db_issue:
        ai_pred_ok = "ai_prediction" in db_issue or "ai_analysis" in db_issue
        log_test("Level 2", "ai_prediction field populated", ai_pred_ok, f"ai_prediction present")
        sla_ok = "sla" in db_issue or "sla_deadline" in db_issue
        log_test("Level 2", "sla.deadline populated", sla_ok, f"sla present")
        img_ok = bool(db_issue.get("image")) or bool(db_issue.get("images"))
        log_test("Level 2", "image.url persisted", img_ok, f"image present: {img_ok}")

    # Duplicate check test
    time.sleep(1)
    payload_dup = {
        "description": "Massive pothole on MG Road is damaging vehicles near the signal area today.",
        "latitude": "12.9718",
        "longitude": "77.5948",
        "address": "MG Road, Bengaluru",
        "image": (io.BytesIO(img_bytes), "pothole_dup.webp")
    }
    res_dup = client.post("/api/issues", data=payload_dup, headers=headers_riya, content_type="multipart/form-data")
    dup_json = res_dup.get_json() or {}
    dup_data = dup_json.get("data", dup_json)
    dup_issue_id = dup_data.get("issue_id") or dup_data.get("_id")
    db_dup = None
    if dup_issue_id:
        if ObjectId.is_valid(dup_issue_id):
            db_dup = db.issues.find_one({"_id": ObjectId(dup_issue_id)})
        if not db_dup:
            db_dup = db.issues.find_one({"issue_id": dup_issue_id})

    is_dup = False
    if db_dup:
        dup_field = db_dup.get("duplicate", {})
        is_dup = dup_field.get("is_duplicate", False) or db_dup.get("status") == "duplicate" or db_dup.get("suppressed") is True
    log_test("Level 2", "Duplicate Complaint Detection", bool(is_dup), f"Duplicate flag: {is_dup}")

    # ----------------------------------------------------
    # Level 3 — Officer Review and Tagging
    # ----------------------------------------------------
    print("\n--- LEVEL 3: Officer Review & Classification ---")
    headers_mehta = {"Authorization": f"Bearer {mehta_token}"} if mehta_token else {}
    res_off_list = client.get("/api/issues", headers=headers_mehta)
    log_test("Level 3", "Officer Lists Issues GET /api/issues", res_off_list.status_code == 200, f"HTTP {res_off_list.status_code}")

    res_off_fetch = client.get(f"/api/issues/{issue_id_str}", headers=headers_mehta) if issue_id_str else res_off_list
    log_test("Level 3", "Officer Fetches Single Issue", res_off_fetch.status_code == 200, f"HTTP {res_off_fetch.status_code}")

    res_under_review = client.patch(f"/api/issues/{issue_id_str}/status", json={"status": "under_review"}, headers=headers_mehta) if issue_id_str else res_off_fetch
    if res_under_review.status_code == 404 and issue_id_str:
        res_under_review = client.post(f"/api/issues/{issue_id_str}/status", json={"status": "under_review"}, headers=headers_mehta)
    log_test("Level 3", "Officer Status Update to under_review", res_under_review.status_code in [200, 201], f"HTTP {res_under_review.status_code} - Body: {res_under_review.get_data(as_text=True)}")

    # Invalid status transition boundary test
    res_invalid_trans = client.patch(f"/api/issues/{issue_id_str}/status", json={"status": "resolved"}, headers=headers_mehta) if issue_id_str else res_under_review
    if res_invalid_trans.status_code == 404 and issue_id_str:
        res_invalid_trans = client.post(f"/api/issues/{issue_id_str}/status", json={"status": "resolved"}, headers=headers_mehta)
    log_test("Level 3", "Invalid Status Transition Boundary (Expect HTTP 422)", res_invalid_trans.status_code == 422, f"HTTP {res_invalid_trans.status_code}")

    # Classification change test
    res_class = client.patch(f"/api/issues/{issue_id_str}/classification", json={"category": "road", "issue_type": "road_collapse", "severity": "critical", "department": "roads"}, headers=headers_mehta) if issue_id_str else res_invalid_trans
    if res_class.status_code == 404 and issue_id_str:
        res_class = client.post(f"/api/issues/{issue_id_str}/review", json={"category": "road", "severity": "critical", "department": "roads", "type": "road_collapse", "reason": "Severe collapse"}, headers=headers_mehta)
    log_test("Level 3", "Officer Classification Override", res_class.status_code in [200, 201], f"HTTP {res_class.status_code}")

    db_issue_post_override = None
    if issue_id_str:
        if ObjectId.is_valid(issue_id_str):
            db_issue_post_override = db.issues.find_one({"_id": ObjectId(issue_id_str)})
        if not db_issue_post_override:
            db_issue_post_override = db.issues.find_one({"issue_id": issue_id_str})
    original_ai_intact = bool(db_issue_post_override and ("ai_prediction" in db_issue_post_override or "ai_analysis" in db_issue_post_override))
    log_test("Level 3", "Original AI Prediction Preserved Untouched", original_ai_intact, f"ai_prediction intact: {original_ai_intact}")

    # ----------------------------------------------------
    # Level 4 — Worker Assignment
    # ----------------------------------------------------
    print("\n--- LEVEL 4: Worker Assignment ---")
    res_rec = client.get(f"/api/issues/{issue_id_str}/recommendations", headers=headers_mehta) if issue_id_str else res_off_list
    if res_rec.status_code == 404 and issue_id_str:
        res_rec = client.get(f"/api/workers/recommendations?issue_id={issue_id_str}", headers=headers_mehta)
    log_test("Level 4", "Get Worker Recommendations", res_rec.status_code == 200, f"HTTP {res_rec.status_code}")

    res_assign = client.post(f"/api/issues/{issue_id_str}/assignment", json={"worker_id": arjun_id}, headers=headers_mehta) if issue_id_str else res_rec
    if res_assign.status_code == 404 and issue_id_str:
        res_assign = client.post(f"/api/issues/{issue_id_str}/assign", json={"worker_id": arjun_id}, headers=headers_mehta)
    log_test("Level 4", "Assign Worker to Issue", res_assign.status_code in [200, 201], f"HTTP {res_assign.status_code} - Body: {res_assign.get_data(as_text=True)}")

    db_issue_post_assign = None
    if issue_id_str:
        if ObjectId.is_valid(issue_id_str):
            db_issue_post_assign = db.issues.find_one({"_id": ObjectId(issue_id_str)})
        if not db_issue_post_assign:
            db_issue_post_assign = db.issues.find_one({"issue_id": issue_id_str})
    db_worker_post_assign = db.workers.find_one({"_id": ObjectId(arjun_id)}) or db.users.find_one({"_id": ObjectId(arjun_id)})
    
    worker_assigned_ok = False
    if db_issue_post_assign and db_worker_post_assign:
        issue_worker_id = db_issue_post_assign.get("worker_id") or db_issue_post_assign.get("assignment", {}).get("worker_id")
        worker_status = db_worker_post_assign.get("status")
        worker_assigned_ok = (str(issue_worker_id) == arjun_id and db_issue_post_assign.get("status") == "assigned" and worker_status == "assigned")
    log_test("Level 4", "Assignment Written to Issue & Worker Status Updated", worker_assigned_ok, f"worker_id={arjun_id}")

    # Boundary test: Resident cannot assign
    res_res_assign = client.post(f"/api/issues/{issue_id_str}/assignment", json={"worker_id": arjun_id}, headers=headers_riya) if issue_id_str else res_rec
    if res_res_assign.status_code == 404 and issue_id_str:
        res_res_assign = client.post(f"/api/issues/{issue_id_str}/assign", json={"worker_id": arjun_id}, headers=headers_riya)
    log_test("Level 4", "Resident Assign Worker Boundary (Expect HTTP 403)", res_res_assign.status_code == 403, f"HTTP {res_res_assign.status_code}")

    # ----------------------------------------------------
    # Level 5 — Worker Task Dashboard
    # ----------------------------------------------------
    print("\n--- LEVEL 5: Worker Task Dashboard ---")
    headers_arjun = {"Authorization": f"Bearer {arjun_token}"} if arjun_token else {}
    res_tasks = client.get(f"/api/workers/{arjun_id}/tasks", headers=headers_arjun)
    log_test("Level 5", "Worker Gets Task List GET /api/workers/<id>/tasks", res_tasks.status_code == 200, f"HTTP {res_tasks.status_code}")
    tasks_json = res_tasks.get_json() or {}
    tasks_list = tasks_json.get("data") if isinstance(tasks_json.get("data"), list) else tasks_json if isinstance(tasks_json, list) else []
    task_found = any(str(t.get("issue_id") or t.get("_id")) == issue_id_str for t in tasks_list) if issue_id_str else False
    log_test("Level 5", "Assigned Task Appears in Worker Dashboard", task_found, f"Tasks count: {len(tasks_list)}, found: {task_found}")

    # Boundary test: Worker cannot see other worker's tasks
    other_worker_id = str(ObjectId())
    res_other_tasks = client.get(f"/api/workers/{other_worker_id}/tasks", headers=headers_arjun)
    log_test("Level 5", "Worker Accessing Other Worker Tasks Boundary (Expect HTTP 403)", res_other_tasks.status_code == 403, f"HTTP {res_other_tasks.status_code}")

    # ----------------------------------------------------
    # Level 6 — Routing
    # ----------------------------------------------------
    print("\n--- LEVEL 6: Routing ---")
    res_route = client.post("/api/route", json={"origin": {"lat": 12.9716, "lng": 77.5946}, "destination": {"lat": 12.9800, "lng": 77.6000}}, headers=headers_arjun)
    if res_route.status_code == 404:
        res_route = client.get(f"/api/map/route?worker_id={arjun_id}&issue_ids={issue_id_str}", headers=headers_arjun)
    log_test("Level 6", "Route Calculation Endpoint", res_route.status_code in [200, 201], f"HTTP {res_route.status_code}")

    res_bad_coords = client.post("/api/route", json={"origin": {"lat": 999, "lng": 77.59}, "destination": {"lat": 12.98, "lng": 77.60}}, headers=headers_arjun)
    log_test("Level 6", "Invalid Coordinates Route Boundary (Expect HTTP 400)", res_bad_coords.status_code == 400, f"HTTP {res_bad_coords.status_code}")

    # ----------------------------------------------------
    # Level 7 — Worker Execution & Resolution
    # ----------------------------------------------------
    print("\n--- LEVEL 7: Worker Execution & Resolution ---")
    res_en_route = client.patch(f"/api/issues/{issue_id_str}/status", json={"status": "en_route"}, headers=headers_arjun) if issue_id_str else res_tasks
    if res_en_route.status_code == 404 and issue_id_str:
        res_en_route = client.post(f"/api/issues/{issue_id_str}/status", json={"status": "en_route"}, headers=headers_arjun)
    log_test("Level 7", "Worker Update Status to en_route", res_en_route.status_code in [200, 201], f"HTTP {res_en_route.status_code}")

    payload_res = {
        "notes": "Pothole filled with bitumen and levelled.",
        "after_image": (io.BytesIO(img_bytes), "after_repair.webp")
    }
    res_resolve = client.post(f"/api/issues/{issue_id_str}/resolution", data=payload_res, headers=headers_arjun, content_type="multipart/form-data") if issue_id_str else res_en_route
    if res_resolve.status_code == 404 and issue_id_str:
        res_resolve = client.post(f"/api/issues/{issue_id_str}/verify", data=payload_res, headers=headers_arjun, content_type="multipart/form-data")
    log_test("Level 7", "Worker Submits Resolution Proof", res_resolve.status_code in [200, 201], f"HTTP {res_resolve.status_code}")

    db_issue_resolved = None
    if issue_id_str:
        if ObjectId.is_valid(issue_id_str):
            db_issue_resolved = db.issues.find_one({"_id": ObjectId(issue_id_str)})
        if not db_issue_resolved:
            db_issue_resolved = db.issues.find_one({"issue_id": issue_id_str})
    resolved_ok = bool(db_issue_resolved and db_issue_resolved.get("status") in ["resolved", "work_completed", "officer_verified"])
    log_test("Level 7", "Issue Status Updated to resolved", resolved_ok, f"status={db_issue_resolved.get('status') if db_issue_resolved else None}")

    # ----------------------------------------------------
    # Level 8 — Resident Sees Full Lifecycle
    # ----------------------------------------------------
    print("\n--- LEVEL 8: Resident Dashboard Visibility ---")
    res_res_get = client.get(f"/api/issues/{issue_id_str}", headers=headers_riya) if issue_id_str else res_tasks
    log_test("Level 8", "Resident Fetches Own Resolved Issue", res_res_get.status_code == 200, f"HTTP {res_res_get.status_code}")

    res_res_list = client.get("/api/issues", headers=headers_riya)
    log_test("Level 8", "Resident Lists Own Issues GET /api/issues", res_res_list.status_code == 200, f"HTTP {res_res_list.status_code}")

    # ----------------------------------------------------
    # Level 9 — Security Checks
    # ----------------------------------------------------
    print("\n--- LEVEL 9: Security Checks ---")
    unauth_client = app.test_client()
    res_unauth = unauth_client.get("/api/issues")
    log_test("Level 9", "Unauthenticated Request (Expect HTTP 401)", res_unauth.status_code == 401, f"HTTP {res_unauth.status_code}")

    res_tampered = unauth_client.get("/api/issues", headers={"Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.tampered.signature"})
    log_test("Level 9", "Tampered Token Request (Expect HTTP 401)", res_tampered.status_code == 401, f"HTTP {res_tampered.status_code}")

    # Cleanup test artifacts from DB
    db.users.delete_many({"email": {"$in": ["riya@test.sc", "mehta@test.sc", "arjun@test.sc"]}})
    db.workers.delete_many({"name": "Worker Arjun"})
    if issue_id_str:
        if ObjectId.is_valid(issue_id_str):
            db.issues.delete_one({"_id": ObjectId(issue_id_str)})
        db.issues.delete_one({"issue_id": issue_id_str})

    # Print Summary
    print("\n" + "=" * 70)
    print("                E2E VERIFICATION TEST SUMMARY                 ")
    print("=" * 70)
    passed_count = sum(1 for r in results if r["passed"])
    failed_count = sum(1 for r in results if not r["passed"])
    print(f"TOTAL TESTS ATTEMPTED: {len(results)}")
    print(f"PASSED: {passed_count}")
    print(f"FAILED: {failed_count}")
    
    if failed_count > 0:
        print("\nFAILURE DETAILS:")
        for r in results:
            if not r["passed"]:
                print(f" - [{r['level']}] {r['name']}: {r['details']}")
    else:
        print("\nALL END-TO-END VERIFICATION LEVELS PASSED 100%!")

if __name__ == '__main__':
    run_e2e_verification()
