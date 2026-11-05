import os
import pytest
from datetime import datetime, timedelta
from bson import ObjectId
from app import create_app, db
from services.retention_service import purge_expired_verification_documents

@pytest.fixture(scope="module")
def app_instance():
    app = create_app()
    app.config["TESTING"] = True
    return app

def test_verification_doc_retention_purge(app_instance):
    """
    Tests the verification document retention purge service with faked timestamps.
    Documents approved/rejected > 30 days ago must be purged and have an audit log entry.
    Documents approved/rejected < 30 days ago must NOT be purged.
    """
    now = datetime.utcnow()
    test_dir = os.path.join(os.getcwd(), "uploads", "verification_docs")
    os.makedirs(test_dir, exist_ok=True)

    # 1. Create expired approved user (40 days ago) with a dummy file
    old_approved_file = "test_doc_expired_approved.jpg"
    with open(os.path.join(test_dir, old_approved_file), "w") as f:
        f.write("dummy doc content")

    user_old_approved_id = db.users.insert_one({
        "email": "retention_old_approved@test.local",
        "verified": True,
        "verification_status": "approved",
        "verified_at": now - timedelta(days=40),
        "verification_doc": f"/files/verification_docs/{old_approved_file}"
    }).inserted_id

    # 2. Create expired rejected user (35 days ago) with a dummy file
    old_rejected_file = "test_doc_expired_rejected.jpg"
    with open(os.path.join(test_dir, old_rejected_file), "w") as f:
        f.write("dummy doc content")

    user_old_rejected_id = db.users.insert_one({
        "email": "retention_old_rejected@test.local",
        "verified": False,
        "verification_status": "rejected",
        "rejected_at": now - timedelta(days=35),
        "verification_doc": f"/files/verification_docs/{old_rejected_file}"
    }).inserted_id

    # 3. Create fresh approved user (5 days ago) - must NOT be purged
    fresh_file = "test_doc_fresh.jpg"
    with open(os.path.join(test_dir, fresh_file), "w") as f:
        f.write("dummy doc content")

    user_fresh_id = db.users.insert_one({
        "email": "retention_fresh@test.local",
        "verified": True,
        "verification_status": "approved",
        "verified_at": now - timedelta(days=5),
        "verification_doc": f"/files/verification_docs/{fresh_file}"
    }).inserted_id

    try:
        # Run retention purge with 30 days retention window
        res = purge_expired_verification_documents(db_instance=db, retention_days=30)
        assert res["purged"] >= 2, f"Expected at least 2 files purged, got {res['purged']}"

        # Verify old approved user doc was purged
        u_old_app = db.users.find_one({"_id": user_old_approved_id})
        assert u_old_app.get("verification_doc") is None
        assert u_old_app.get("verification_doc_purged") is True
        assert not os.path.exists(os.path.join(test_dir, old_approved_file))

        # Verify old rejected user doc was purged
        u_old_rej = db.users.find_one({"_id": user_old_rejected_id})
        assert u_old_rej.get("verification_doc") is None
        assert u_old_rej.get("verification_doc_purged") is True
        assert not os.path.exists(os.path.join(test_dir, old_rejected_file))

        # Verify fresh user doc was PRESERVED
        u_fresh = db.users.find_one({"_id": user_fresh_id})
        assert u_fresh.get("verification_doc") == f"/files/verification_docs/{fresh_file}"
        assert os.path.exists(os.path.join(test_dir, fresh_file))

        # Verify audit_logs entries
        audit_entries = list(db.audit_logs.find({
            "action": "verification_doc_purged",
            "target_user_id": {"$in": [str(user_old_approved_id), str(user_old_rejected_id)]}
        }))
        assert len(audit_entries) == 2, f"Expected 2 audit log entries, found {len(audit_entries)}"

    finally:
        # Cleanup
        db.users.delete_many({"_id": {"$in": [user_old_approved_id, user_old_rejected_id, user_fresh_id]}})
        db.audit_logs.delete_many({"target_user_id": {"$in": [str(user_old_approved_id), str(user_old_rejected_id)]}})
        for f_name in [old_approved_file, old_rejected_file, fresh_file]:
            p = os.path.join(test_dir, f_name)
            if os.path.exists(p):
                os.remove(p)
