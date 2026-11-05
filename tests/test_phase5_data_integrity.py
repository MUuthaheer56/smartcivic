import pytest
import os
import concurrent.futures
from datetime import datetime, timedelta
from bson import ObjectId

from app import create_app, db

@pytest.fixture(scope="module")
def app_instance():
    app = create_app()
    app.config["TESTING"] = True
    return app

def test_explain_plan_no_in_memory_sort(app_instance):
    """
    Q2 Benchmark check: Ward feed query (ward + created_at DESC)
    MUST use compound index ward_1_created_at_-1 without an in-memory SORT stage.
    """
    explain_res = db.issues.find({"ward": "ward_1"}).sort([("created_at", -1)]).explain()
    winning = explain_res.get("queryPlanner", {}).get("winningPlan", {})
    
    stage = winning.get("stage")
    assert stage != "SORT", f"Query plan contains in-memory SORT stage: {winning}"
    
    # Check index name used
    index_name = winning.get("inputStage", {}).get("indexName")
    assert index_name == "ward_1_created_at_-1", f"Expected index 'ward_1_created_at_-1', got '{index_name}'"

def test_bounded_map_query(app_instance):
    """
    GET /api/map/issues enforces a default limit (e.g. 250)
    and prevents unbounded retrieval of all documents.
    """
    client = app_instance.test_client()
    officer_id = db.users.insert_one({
        "email": f"officer_{ObjectId()}@test.local",
        "role": "officer",
        "ward": "all",
        "status": "active"
    }).inserted_id
    
    import jwt
    token = jwt.encode(
        {"user_id": str(officer_id), "role": "officer", "ward": "all", "type": "access"},
        app_instance.config["JWT_SECRET"],
        algorithm="HS256"
    )
    
    res = client.get(
        "/api/map/issues?limit=5",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert len(data["data"]) <= 5

def test_atomic_community_confirmation_parallel(app_instance):
    """
    Parallel confirmation requests by the same citizen cannot duplicate
    confirmations or corrupt confirmation_count.
    """
    from services.complaint_service import add_community_confirmation
    
    author_id = ObjectId()
    citizen_id = ObjectId()
    
    issue_id = db.issues.insert_one({
        "title": "Broken bench",
        "description": "Park bench broken",
        "citizen_id": author_id,
        "ward": "12",
        "status": "submitted",
        "community_confirmations": [],
        "confirmation_count": 0
    }).inserted_id
    
    successes = 0
    errors = 0
    
    def confirm():
        try:
            add_community_confirmation(str(issue_id), str(citizen_id), "I see this too")
            return True
        except ValueError:
            return False

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(confirm) for _ in range(8)]
        for f in concurrent.futures.as_completed(futures):
            if f.result():
                successes += 1
            else:
                errors += 1
                
    assert successes == 1, f"Expected exactly 1 success, got {successes}"
    assert errors == 7, f"Expected 7 rejections, got {errors}"
    
    updated = db.issues.find_one({"_id": issue_id})
    assert updated["confirmation_count"] == 1
    assert len(updated["community_confirmations"]) == 1

def test_atomic_worker_assignment_parallel(app_instance):
    """
    Parallel assignment requests for the same issue to different workers
    result in exactly one successful assignment without over-assignment.
    """
    from services.assignment_service import assign_worker
    
    issue_id = db.issues.insert_one({
        "title": "Water pipe leak",
        "status": "submitted",
        "category": "water_supply",
        "type": "leak",
        "ward": "12",
        "worker_id": None
    }).inserted_id
    
    worker1_id = db.users.insert_one({
        "email": f"w1_{ObjectId()}@test.local",
        "role": "worker",
        "active_assignments": 0,
        "is_available": True
    }).inserted_id
    
    worker2_id = db.users.insert_one({
        "email": f"w2_{ObjectId()}@test.local",
        "role": "worker",
        "active_assignments": 0,
        "is_available": True
    }).inserted_id
    
    officer_id = str(ObjectId())
    results = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(assign_worker, str(issue_id), str(worker1_id), officer_id)
        f2 = executor.submit(assign_worker, str(issue_id), str(worker2_id), officer_id)
        
        for f in [f1, f2]:
            try:
                res = f.result()
                results.append("success")
            except Exception as e:
                results.append(f"error: {e}")

    assert results.count("success") == 1, f"Expected exactly 1 success: {results}"
    
    # Confirm issue worker_id is assigned to only one worker
    final_issue = db.issues.find_one({"_id": issue_id})
    assert final_issue["worker_id"] in [worker1_id, worker2_id]

def test_sla_escalation_spacing(app_instance):
    """
    FLOW-07 fix: An issue overdue past SLA does NOT cascade through L1 -> L2 -> L3
    on consecutive runs if 24 hours have not passed since last escalation.
    """
    from services.sla_escalation import run_escalation_check
    
    now = datetime.utcnow()
    past_deadline = now - timedelta(hours=80)
    
    issue_id = db.issues.insert_one({
        "title": "Unattended pothole",
        "status": "submitted",
        "emergency": False,
        "priority": "P3",
        "created_at": past_deadline,
        "escalation_level": 0
    }).inserted_id
    
    # First escalation: L0 -> L1
    run_escalation_check()
    iss1 = db.issues.find_one({"_id": issue_id})
    assert iss1["escalation_level"] == 1
    assert iss1.get("last_escalated_at") is not None
    
    # Immediate second run (5 mins later): MUST stay at L1
    run_escalation_check()
    iss2 = db.issues.find_one({"_id": issue_id})
    assert iss2["escalation_level"] == 1, "Escalation should not cascade immediately without spacing"

def test_backup_restore_roundtrip(app_instance):
    """
    DB-01: Create a backup, restore it using run_restore(),
    and verify that indexes are automatically rebuilt and intact.
    """
    from scripts.backup_db import run_backup, run_restore
    
    # Run backup
    backup_file = run_backup()
    assert backup_file is not None
    assert os.path.exists(backup_file)
    
    backup_filename = os.path.basename(backup_file)
    
    # Run restore
    restore_ok = run_restore(backup_filename)
    assert restore_ok is True
    
    # Check that indexes exist after restore
    indexes = db.issues.index_information()
    assert "ward_1_created_at_-1" in indexes, f"Index missing after restore: {indexes.keys()}"
    assert "location_2dsphere" in indexes, f"2dsphere index missing after restore: {indexes.keys()}"
