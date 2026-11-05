"""
Stage 1 Attack Uploads Test Suite
Executes the five Stage 1 attack upload vectors against SmartCivic:
1. Malicious PHP script disguised as JPG (shell.php.jpg)
2. Path traversal attack in upload filename (../../../../etc/cron.d/malicious.jpg)
3. Malicious SVG / Script disguised as image (vector.svg.jpg)
4. Oversized upload payload exceeding MAX_CONTENT_LENGTH (> 8MB)
5. Direct unauthenticated access to legacy /static/uploads and /files/ endpoints
"""
import io
import os
import json
import pytest
from bson import ObjectId
from PIL import Image

from app import create_app, db
from config import Config
from routes.auth import generate_tokens, hash_password


@pytest.fixture
def test_setup():
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    client = app.test_client()

    uid = ObjectId()
    db.users.insert_one({
        "_id": uid,
        "email": "stage1_attacker@smartcivic.test",
        "name": "Stage1 Attacker",
        "password_hash": hash_password("ValidPassword123!"),
        "role": "citizen",
        "ward": "Ward 1",
        "ward_id": "ward_1",
        "verified": True,
        "verification_status": "approved",
        "status": "active"
    })
    token, _ = generate_tokens(str(uid), "citizen", "Ward 1")

    yield {"app": app, "client": client, "token": token, "uid": uid}

    db.users.delete_one({"_id": uid})
    db.issues.delete_many({"citizen_id": uid})


def test_attack_1_disguised_php_script(test_setup):
    """Attack 1: Malicious PHP script renamed to shell.php.jpg"""
    client = test_setup["client"]
    token = test_setup["token"]

    php_payload = b"<?php phpinfo(); system($_GET['cmd']); ?>"
    data = {
        "title": "Stage 1 Attack - Disguised PHP Shell",
        "description": "Attempting remote code execution via disguised JPEG",
        "category": "roads",
        "latitude": "12.9716",
        "longitude": "77.5946",
        "ward_id": "ward_1",
        "image": (io.BytesIO(php_payload), "shell.php.jpg", "image/jpeg")
    }

    client.set_cookie("access_token", token)
    resp = client.post("/api/issues", data=data, content_type="multipart/form-data")
    print(f"\n[Attack 1] Disguised PHP -> Status: {resp.status_code}")
    print(f"[Attack 1] Response: {resp.get_data(as_text=True)}")
    assert resp.status_code == 400
    res_json = resp.get_json()
    assert res_json.get("success") is False
    assert res_json.get("error", {}).get("code") in ("SECURITY_ERROR", "INVALID_IMAGE", "VALIDATION_ERROR", "BAD_REQUEST")


def test_attack_2_path_traversal_filename(test_setup):
    """Attack 2: Path traversal filename (../../../../etc/cron.d/malicious.jpg)"""
    client = test_setup["client"]
    token = test_setup["token"]

    img = Image.new("RGB", (64, 64), color="red")
    img_bytes = io.BytesIO()
    img.save(img_bytes, format="JPEG")
    img_bytes.seek(0)

    data = {
        "title": "Stage 1 Attack - Path Traversal",
        "description": "Attempting arbitrary file overwrite via traversal in filename",
        "category": "roads",
        "latitude": "12.9716",
        "longitude": "77.5946",
        "ward_id": "ward_1",
        "image": (img_bytes, "../../../../etc/cron.d/malicious.jpg", "image/jpeg")
    }

    client.set_cookie("access_token", token)
    resp = client.post("/api/issues", data=data, content_type="multipart/form-data")
    print(f"\n[Attack 2] Path Traversal -> Status: {resp.status_code}")
    print(f"[Attack 2] Response: {resp.get_data(as_text=True)[:200]}...")
    assert resp.status_code in (201, 200)

    created = db.issues.find_one({"title": "Stage 1 Attack - Path Traversal"})
    assert created is not None
    assert len(created.get("images", [])) > 0
    saved_name = created["images"][0]["filename"]
    print(f"[Attack 2] Saved Filename Sanitized to: {saved_name}")
    assert ".." not in saved_name
    assert "/" not in saved_name
    assert "\\" not in saved_name


def test_attack_3_disguised_svg_xss(test_setup):
    """Attack 3: Malicious SVG / XSS disguised as image"""
    client = test_setup["client"]
    token = test_setup["token"]

    svg_payload = b"<svg xmlns='http://www.w3.org/2000/svg' onload='alert(document.cookie)'></svg>"
    data = {
        "title": "Stage 1 Attack - SVG XSS Vector",
        "description": "Attempting stored XSS via SVG vector upload disguised as JPEG",
        "category": "roads",
        "latitude": "12.9716",
        "longitude": "77.5946",
        "ward_id": "ward_1",
        "image": (io.BytesIO(svg_payload), "vector.svg.jpg", "image/jpeg")
    }

    client.set_cookie("access_token", token)
    resp = client.post("/api/issues", data=data, content_type="multipart/form-data")
    print(f"\n[Attack 3] Disguised SVG -> Status: {resp.status_code}")
    print(f"[Attack 3] Response: {resp.get_data(as_text=True)}")
    assert resp.status_code == 400
    res_json = resp.get_json()
    assert res_json.get("success") is False


def test_attack_4_oversized_payload(test_setup):
    """Attack 4: Oversized payload exceeding MAX_CONTENT_LENGTH (> 8MB)"""
    client = test_setup["client"]
    token = test_setup["token"]

    # 9 MB dummy payload
    oversized_data = b"0" * (9 * 1024 * 1024)
    data = {
        "title": "Stage 1 Attack - Oversized Payload",
        "description": "Attempting DoS via oversized file upload",
        "category": "roads",
        "latitude": "12.9716",
        "longitude": "77.5946",
        "ward_id": "ward_1",
        "image": (io.BytesIO(oversized_data), "huge_bomb.jpg", "image/jpeg")
    }

    client.set_cookie("access_token", token)
    resp = client.post("/api/issues", data=data, content_type="multipart/form-data")
    print(f"\n[Attack 4] Oversized Payload (>8MB) -> Status: {resp.status_code}")
    print(f"[Attack 4] Response: {resp.get_data(as_text=True)[:200]}")
    assert resp.status_code == 413


def test_attack_5_unauthorized_direct_access(test_setup):
    """Attack 5: Unauthenticated access to legacy /static/uploads and /files/ endpoints"""
    client = test_setup["client"]

    # 1. Direct GET to legacy /static/uploads/ must return 404
    resp_static = client.get("/static/uploads/verification_docs/confidential_id.jpg")
    print(f"\n[Attack 5a] Legacy /static/uploads -> Status: {resp_static.status_code}")
    assert resp_static.status_code == 404

    # 2. Unauthenticated GET to /files/verification_docs/ must return 401
    resp_unauth = client.get("/files/verification_docs/confidential_id.jpg")
    print(f"[Attack 5b] Unauthenticated /files/ -> Status: {resp_unauth.status_code}")
    print(f"[Attack 5b] Response (truncated): {resp_unauth.get_data(as_text=True)[:100]}")
    assert resp_unauth.status_code == 401
