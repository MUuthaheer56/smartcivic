"""
SmartCivic — F2 Test Suite: Private Uploads and Access Control
Validates:
1. Anonymous request gets 401
2. Another citizen requesting someone's ID doc gets 403
3. Legacy /static/uploads/... returns 404
4. The reporter and officer get 200
5. Invalid/unknown kind returns 404
6. Non-existent file returns 404
"""
import os
import pytest
from bson import ObjectId
from app import create_app, db
from config import Config
from routes.auth import generate_tokens

@pytest.fixture
def app_instance():
    app = create_app()
    app.config["TESTING"] = True
    return app

@pytest.fixture
def client(app_instance):
    return app_instance.test_client()

@pytest.fixture
def sample_files(app_instance):
    # Ensure test files exist in private uploads folders
    test_doc = "test_verification_doc.png"
    test_issue = "test_issue_photo.jpg"
    
    docs_dir = os.path.join(Config.PRIVATE_UPLOAD_DIR, "verification_docs")
    issues_dir = os.path.join(Config.PRIVATE_UPLOAD_DIR, "issues")
    os.makedirs(docs_dir, exist_ok=True)
    os.makedirs(issues_dir, exist_ok=True)
    
    doc_path = os.path.join(docs_dir, test_doc)
    issue_path = os.path.join(issues_dir, test_issue)
    
    with open(doc_path, "wb") as f:
        f.write(b"PNG_MOCK_CONTENT")
    with open(issue_path, "wb") as f:
        f.write(b"JPEG_MOCK_CONTENT")
        
    yield {
        "doc_filename": test_doc,
        "doc_path": doc_path,
        "issue_filename": test_issue,
        "issue_path": issue_path
    }
    
    # Cleanup files
    if os.path.exists(doc_path):
        os.remove(doc_path)
    if os.path.exists(issue_path):
        os.remove(issue_path)

def test_anonymous_request_gets_401(client, sample_files):
    # Trying to access private file without token returns 401
    resp = client.get(f"/files/verification_docs/{sample_files['doc_filename']}")
    assert resp.status_code == 401

    resp2 = client.get(f"/files/issues/{sample_files['issue_filename']}")
    assert resp2.status_code == 401

def test_legacy_static_uploads_returns_404(client, sample_files):
    # Accessing legacy static path returns 404 (static uploads folder was removed)
    resp = client.get(f"/static/uploads/verification_docs/{sample_files['doc_filename']}")
    assert resp.status_code == 404

    resp2 = client.get(f"/static/uploads/issues/{sample_files['issue_filename']}")
    assert resp2.status_code == 404

def test_another_citizen_requesting_id_doc_gets_403(app_instance, client, sample_files):
    owner_id = ObjectId()
    other_citizen_id = ObjectId()
    
    # Insert owner and other citizen into database
    with app_instance.app_context():
        db.users.insert_many([
            {
                "_id": owner_id,
                "email": "owner@example.com",
                "role": "resident",
                "verification_doc": f"/files/verification_docs/{sample_files['doc_filename']}"
            },
            {
                "_id": other_citizen_id,
                "email": "other@example.com",
                "role": "resident",
                "verification_doc": None
            }
        ])
        
        other_token, _ = generate_tokens(str(other_citizen_id), "resident", "Ward 1")
        
    try:
        headers = {"Authorization": f"Bearer {other_token}"}
        resp = client.get(f"/files/verification_docs/{sample_files['doc_filename']}", headers=headers)
        assert resp.status_code == 403
    finally:
        with app_instance.app_context():
            db.users.delete_many({"_id": {"$in": [owner_id, other_citizen_id]}})

def test_reporter_and_officer_get_200(app_instance, client, sample_files):
    reporter_id = ObjectId()
    officer_id = ObjectId()
    issue_id = ObjectId()
    
    with app_instance.app_context():
        db.users.insert_many([
            {
                "_id": reporter_id,
                "email": "reporter@example.com",
                "role": "resident",
                "ward": "Ward 1"
            },
            {
                "_id": officer_id,
                "email": "officer@example.com",
                "role": "officer",
                "department": "roads",
                "ward": "Ward 1"
            }
        ])
        
        db.issues.insert_one({
            "_id": issue_id,
            "citizen_id": reporter_id,
            "department": "roads",
            "images": [{
                "filename": sample_files["issue_filename"],
                "url": f"/files/issues/{sample_files['issue_filename']}",
                "filepath": sample_files["issue_path"]
            }]
        })
        
        reporter_token, _ = generate_tokens(str(reporter_id), "resident", "Ward 1")
        officer_token, _ = generate_tokens(str(officer_id), "officer", "Ward 1")
        
    try:
        # 1. Reporter gets 200
        rep_headers = {"Authorization": f"Bearer {reporter_token}"}
        resp_rep = client.get(f"/files/issues/{sample_files['issue_filename']}", headers=rep_headers)
        assert resp_rep.status_code == 200
        assert resp_rep.data == b"JPEG_MOCK_CONTENT"
        
        # 2. Officer gets 200
        off_headers = {"Authorization": f"Bearer {officer_token}"}
        resp_off = client.get(f"/files/issues/{sample_files['issue_filename']}", headers=off_headers)
        assert resp_off.status_code == 200
        assert resp_off.data == b"JPEG_MOCK_CONTENT"
    finally:
        with app_instance.app_context():
            db.users.delete_many({"_id": {"$in": [reporter_id, officer_id]}})
            db.issues.delete_one({"_id": issue_id})

def test_invalid_kind_returns_404(app_instance, client, sample_files):
    reporter_id = ObjectId()
    with app_instance.app_context():
        token, _ = generate_tokens(str(reporter_id), "resident", "Ward 1")
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.get(f"/files/unknown_kind/{sample_files['issue_filename']}", headers=headers)
    assert resp.status_code == 404

def test_acceptance_no_login_uploads_do_not_load(client, sample_files):
    """
    Acceptance check: In a private browser window with no login,
    none of the sample upload URLs load, old or new.
    """
    # 1. Old URL: /static/uploads/... returns 404 (does not load)
    old_doc_url = f"/static/uploads/verification_docs/{sample_files['doc_filename']}"
    old_issue_url = f"/static/uploads/issues/{sample_files['issue_filename']}"
    assert client.get(old_doc_url).status_code == 404
    assert client.get(old_issue_url).status_code == 404

    # 2. New URL: /files/... returns 401 Unauthorized (does not load)
    new_doc_url = f"/files/verification_docs/{sample_files['doc_filename']}"
    new_issue_url = f"/files/issues/{sample_files['issue_filename']}"
    assert client.get(new_doc_url).status_code == 401
    assert client.get(new_issue_url).status_code == 401
