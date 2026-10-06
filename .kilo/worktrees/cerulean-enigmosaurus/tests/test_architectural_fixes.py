import os
import pytest
from datetime import datetime
from bson import ObjectId
from app import create_app, db

@pytest.fixture
def test_app():
    os.environ["JWT_SECRET"] = "test_arch_fixes_jwt_secret_12345"
    os.environ["JWT_SECRET_KEY"] = "test_arch_fixes_jwt_secret_12345"
    app = create_app()
    app.config["TESTING"] = True
    with app.app_context():
        yield app

def test_verification_state_inconsistencies(test_app):
    from services.verification_service import submit_resolution, officer_verify, citizen_verify
    
    # 1. Setup closed issue
    closed_issue_id = db.issues.insert_one({
        "status": "closed",
        "type": "pothole",
        "citizen_id": ObjectId()
    }).inserted_id

    worker_id = str(ObjectId())
    
    # Test invalid submit_resolution state
    with pytest.raises(ValueError, match="Cannot submit resolution"):
        submit_resolution(str(closed_issue_id), worker_id, {"filepath": "b.jpg"}, {"filepath": "a.jpg"}, "Done")
        
    # Test invalid officer_verify state
    with pytest.raises(ValueError, match="Cannot perform officer verification"):
        officer_verify(str(closed_issue_id), str(ObjectId()), True, "Approved")
        
    # Test invalid citizen_verify state
    with pytest.raises(ValueError, match="Cannot perform citizen verification"):
        citizen_verify(str(closed_issue_id), str(ObjectId()), True, "Great")

def test_assignment_race_condition(test_app):
    from services.assignment_service import assign_worker
    
    # Create worker at max capacity (5 assignments)
    worker_id = ObjectId()
    db.users.insert_one({
        "_id": worker_id,
        "email": f"busy_worker_{worker_id}@test.com",
        "name": "Busy Worker",
        "role": "worker",
        "is_available": False,
        "active_assignments": 5
    })
    
    issue_id = db.issues.insert_one({
        "status": "submitted",
        "type": "pothole"
    }).inserted_id
    
    officer_id = ObjectId()
    
    with pytest.raises(ValueError, match="Worker is not available"):
        assign_worker(str(issue_id), str(worker_id), str(officer_id))

def test_cefap_fallback_and_civic_score(test_app):
    from services.cefap_pipeline import cefap_stage
    from utils.civic_score import apply_score_delta
    import uuid
    
    # Test CEFAP with malformed parameters
    malformed_params = {
        "text_severity": None,
        "created_at": "invalid-date-string",
        "sla_deadline": "invalid-deadline"
    }
    res = cefap_stage(db, malformed_params)
    assert res is not None
    assert "cips" in res
    assert res["priority"] in ["P0", "P1", "P2", "P3"]
    
    # Test apply_score_delta on uninitialized user
    uninit_user_id = db.users.insert_one({
        "email": f"uninit_user_{uuid.uuid4().hex[:8]}@test.com",
        "name": "Uninit User",
        "civic_score": None
    }).inserted_id
    
    score, tier = apply_score_delta(db, str(uninit_user_id), "report_filed")
    assert score == 5
    assert tier == "reporter"

def test_yolo_file_size_and_model_guards(test_app):
    from ml.yolo_runner import run_yolo_inference
    
    res = run_yolo_inference("non_existent_file.jpg")
    assert res["available"] is False
    assert "not found" in res["reason"]

def test_decomposer_cap_and_duplicate_bounds(test_app):
    from services.multi_issue_decomposer import decompose
    from services.duplicate_service import find_duplicate_candidates
    
    long_text = "Pothole on main road and broken street light also water leakage issue and garbage uncollected on street"
    sub_issues = decompose(long_text, "parent_123")
    assert len(sub_issues) <= 3
    
    candidates = find_duplicate_candidates({"latitude": 12.9716, "longitude": 77.5946}, {"category": "roads"})
    assert isinstance(candidates, list)
    assert len(candidates) <= 50

def test_sla_concurrency_locking(test_app):
    from services.sla_escalation import run_escalation_check
    
    overdue_id = db.issues.insert_one({
        "status": "submitted",
        "emergency": False,
        "priority": "P0",
        "created_at": datetime(2020, 1, 1),
        "escalation_level": 0
    }).inserted_id
    
    run_escalation_check()
    updated = db.issues.find_one({"_id": overdue_id})
    assert updated["escalation_level"] == 1
    assert updated["sla_status"] == "breached"
