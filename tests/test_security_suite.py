import os
import pytest
import io
from app import create_app
from utils.security import generate_tokens

@pytest.fixture
def client():
    old_jwt_secret = os.environ.get("JWT_SECRET")
    old_jwt_key = os.environ.get("JWT_SECRET_KEY")
    old_invite = os.environ.get("ADMIN_INVITE_CODE")

    os.environ["ADMIN_INVITE_CODE"] = "SMARTCIVIC-ADMIN-TEST"
    app = create_app()
    app.config["TESTING"] = True
    from app import limiter
    limiter.enabled = False
    app.config["ADMIN_INVITE_CODE"] = "SMARTCIVIC-ADMIN-TEST"
    with app.test_client() as client:
        yield client

    if old_jwt_secret is not None:
        os.environ["JWT_SECRET"] = old_jwt_secret
    else:
        os.environ.pop("JWT_SECRET", None)

    if old_jwt_key is not None:
        os.environ["JWT_SECRET_KEY"] = old_jwt_key
    else:
        os.environ.pop("JWT_SECRET_KEY", None)

    if old_invite is not None:
        os.environ["ADMIN_INVITE_CODE"] = old_invite
    else:
        os.environ.pop("ADMIN_INVITE_CODE", None)

def test_staff_registration_blocked_without_code(client):
    response = client.post('/api/auth/register', json={
        "email": "unauth_officer@test.com",
        "name": "Unauth Officer",
        "password": "SecurePassword123!",
        "role": "officer",
        "ward": "Ward 1"
    })
    assert response.status_code == 403
    data = response.get_json() or {}
    err = data.get("error", {})
    err_msg = err.get("message") if isinstance(err, dict) else str(err)
    assert "Unauthorized" in err_msg or "Invite Code" in err_msg or response.status_code == 403

def test_refresh_token_rejected_as_access(client):
    with client.application.app_context():
        _, refresh_token = generate_tokens("123456789012345678901234", "citizen", "Ward 1")
    
    response = client.get('/api/issues', headers={
        "Authorization": f"Bearer {refresh_token}"
    })
    assert response.status_code in [401, 403]

def test_malicious_file_upload_rejection(client):
    from app import db
    from bson import ObjectId
    user_id = ObjectId()
    db.users.delete_many({"email": "sec_test_citizen@test.com"})
    db.users.insert_one({
        "_id": user_id,
        "email": "sec_test_citizen@test.com",
        "name": "Sec Test Citizen",
        "role": "citizen",
        "verified": True,
        "verification_status": "approved",
        "status": "active",
        "ward": "Ward 1"
    })
    with client.application.app_context():
        access_token, _ = generate_tokens(str(user_id), "citizen", "Ward 1")
    
    fake_file = (io.BytesIO(b"<html><body><h1>XSS</h1></body></html>"), "exploit.jpg")
    
    response = client.post('/api/issues', data={
        "description": "Testing malicious upload filter bounds",
        "latitude": "12.9716",
        "longitude": "77.5946",
        "address": "MG Road, Bengaluru",
        "image": fake_file
    }, headers={
        "Authorization": f"Bearer {access_token}"
    }, content_type='multipart/form-data')
    
    assert response.status_code in [400, 422]
