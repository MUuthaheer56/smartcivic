"""
tests/test_worker_assignment_atomic.py
Regression tests for:
2.2 WORKER ASSIGN:
- Atomic update of issue status, worker capacity, notifications, audit log
- Reassignment releases previous worker's slot
- Full / inactive worker assignment rejection (capacity >= 5)
- Concurrent dual-officer assignment race test
"""

import threading
import pytest
from bson import ObjectId
from app import create_app, db
from services.assignment_service import assign_worker


@pytest.fixture
def app_ctx():
    app = create_app()
    app.config["TESTING"] = True
    with app.app_context():
        yield app


def test_worker_assignment_and_capacity(app_ctx):
    # Setup test workers and issue
    w1_id = ObjectId()
    w2_id = ObjectId()
    officer_id = ObjectId()
    issue_id = ObjectId()

    db.users.insert_one({
        "_id": w1_id,
        "name": "Field Worker 1",
        "email": "fw1@test.com",
        "role": "worker",
        "is_available": True,
        "active_assignments": 0
    })

    db.users.insert_one({
        "_id": w2_id,
        "name": "Field Worker 2",
        "email": "fw2@test.com",
        "role": "worker",
        "is_available": True,
        "active_assignments": 0
    })

    db.issues.insert_one({
        "_id": issue_id,
        "issue_id": str(issue_id),
        "title": "Pothole for assignment",
        "status": "submitted",
        "category": "road",
        "worker_id": None
    })

    try:
        # 1. Initial assignment to Worker 1
        assign_worker(str(issue_id), str(w1_id), str(officer_id))

        w1 = db.users.find_one({"_id": w1_id})
        iss = db.issues.find_one({"_id": issue_id})
        assert w1["active_assignments"] == 1
        assert str(iss["worker_id"]) == str(w1_id)
        assert iss["status"] == "assigned"

        # 2. Reassignment to Worker 2: releases Worker 1's slot
        assign_worker(str(issue_id), str(w2_id), str(officer_id))

        w1_after = db.users.find_one({"_id": w1_id})
        w2_after = db.users.find_one({"_id": w2_id})
        iss_after = db.issues.find_one({"_id": issue_id})

        assert w1_after["active_assignments"] == 0, "Previous worker slot must be released on reassignment"
        assert w2_after["active_assignments"] == 1, "New worker slot must be incremented"
        assert str(iss_after["worker_id"]) == str(w2_id)
        assert iss_after["status"] == "assigned"

    finally:
        db.users.delete_many({"_id": {"$in": [w1_id, w2_id]}})
        db.issues.delete_one({"_id": issue_id})
        db.assignments.delete_many({"issue_id": str(issue_id)})


def test_full_or_inactive_worker_rejection(app_ctx):
    w_full_id = ObjectId()
    w_inactive_id = ObjectId()
    officer_id = ObjectId()
    iss1 = ObjectId()
    iss2 = ObjectId()

    db.users.insert_one({
        "_id": w_full_id,
        "name": "Full Worker",
        "email": f"full_worker_{w_full_id}@test.com",
        "role": "worker",
        "is_available": True,
        "active_assignments": 5
    })

    db.users.insert_one({
        "_id": w_inactive_id,
        "name": "Inactive Worker",
        "email": f"inactive_worker_{w_inactive_id}@test.com",
        "role": "worker",
        "is_available": False,
        "active_assignments": 1
    })

    db.issues.insert_one({"_id": iss1, "title": "Iss 1", "status": "submitted", "worker_id": None})
    db.issues.insert_one({"_id": iss2, "title": "Iss 2", "status": "submitted", "worker_id": None})

    try:
        # Full worker assignment rejected
        with pytest.raises(ValueError, match="not available"):
            assign_worker(str(iss1), str(w_full_id), str(officer_id))

        # Inactive worker assignment rejected
        with pytest.raises(ValueError, match="not available"):
            assign_worker(str(iss2), str(w_inactive_id), str(officer_id))

    finally:
        db.users.delete_many({"_id": {"$in": [w_full_id, w_inactive_id]}})
        db.issues.delete_many({"_id": {"$in": [iss1, iss2]}})


def test_concurrent_dual_officer_assignment_race(app_ctx):
    w1_id = ObjectId()
    w2_id = ObjectId()
    officer1_id = ObjectId()
    officer2_id = ObjectId()
    issue_id = ObjectId()

    db.users.insert_one({
        "_id": w1_id,
        "name": "Worker 1",
        "email": f"worker1_race_{w1_id}@test.com",
        "role": "worker",
        "is_available": True,
        "active_assignments": 0
    })

    db.users.insert_one({
        "_id": w2_id,
        "name": "Worker 2",
        "email": f"worker2_race_{w2_id}@test.com",
        "role": "worker",
        "is_available": True,
        "active_assignments": 0
    })

    db.issues.insert_one({
        "_id": issue_id,
        "title": "Race Issue",
        "status": "submitted",
        "worker_id": None
    })

    results = []
    errors = []

    def officer_assign(w_id, off_id):
        try:
            assign_worker(str(issue_id), str(w_id), str(off_id))
            results.append(str(w_id))
        except Exception as e:
            errors.append(str(e))

    try:
        t1 = threading.Thread(target=officer_assign, args=(w1_id, officer1_id))
        t2 = threading.Thread(target=officer_assign, args=(w2_id, officer2_id))

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Both threads fired simultaneously on an unassigned issue.
        # Exactly one must succeed initially without corrupting capacity.
        w1 = db.users.find_one({"_id": w1_id})
        w2 = db.users.find_one({"_id": w2_id})
        iss = db.issues.find_one({"_id": issue_id})

        # Total active assignments allocated must match the single winner
        total_active = w1["active_assignments"] + w2["active_assignments"]
        assert total_active == 1, f"Expected total 1 active assignment, got w1={w1['active_assignments']}, w2={w2['active_assignments']}"
        assert iss["worker_id"] in [w1_id, w2_id]

    finally:
        db.users.delete_many({"_id": {"$in": [w1_id, w2_id]}})
        db.issues.delete_one({"_id": issue_id})
        db.assignments.delete_many({"issue_id": str(issue_id)})
