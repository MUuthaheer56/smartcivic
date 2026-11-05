import io
import pytest
from bson import ObjectId
from PIL import Image
from app import create_app, db
from routes.auth import generate_tokens

def create_valid_jpeg():
    """Generates a valid minimal 100x100 JPEG image in memory."""
    buf = io.BytesIO()
    img = Image.new("RGB", (100, 100), color=(73, 109, 137))
    img.save(buf, format="JPEG")
    buf.seek(0)
    return buf

@pytest.fixture(scope="module")
def app_instance():
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["RATE_LIMIT_ENABLED"] = False
    yield app

@pytest.fixture(autouse=True)
def clean_db():
    db.users.delete_many({"email": {"$regex": "@smartcivic\\.local$"}})
    db.issues.delete_many({"title": {"$in": ["Broken pipe", "Streetlight off", "Damaged bench"]}})
    yield
    db.users.delete_many({"email": {"$regex": "@smartcivic\\.local$"}})
    db.issues.delete_many({"title": {"$in": ["Broken pipe", "Streetlight off", "Damaged bench"]}})

def test_worker_resolve_accepts_after_image(app_instance):
    """Verify worker can submit resolution proof using mobile-standard 'after_image' file field."""
    worker_id = str(ObjectId())
    db.users.insert_one({
        "_id": ObjectId(worker_id),
        "email": "worker1@smartcivic.local",
        "role": "worker",
        "ward": "Ward 1",
        "verified": True,
        "status": "APPROVED"
    })
    
    issue_id = str(ObjectId())
    db.issues.insert_one({
        "_id": ObjectId(issue_id),
        "title": "Broken pipe",
        "status": "in_progress",
        "worker_id": worker_id,
        "ward": "Ward 1"
    })

    with app_instance.app_context():
        worker_token, _ = generate_tokens(worker_id, "worker", "Ward 1")
    client_test = app_instance.test_client()
    client_test.set_cookie("access_token", worker_token)

    # Create dummy valid image
    image_bytes = create_valid_jpeg()
    
    # Send using 'after_image'
    res = client_test.post(
        f"/api/issues/{issue_id}/resolve",
        data={
            "notes": "Fixed pipe completely",
            "after_image": (image_bytes, "repaired.jpg")
        },
        content_type="multipart/form-data"
    )

    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.get_json()}"
    data = res.get_json()
    assert data["success"] is True

    # Verify updated issue document in DB
    updated = db.issues.find_one({"_id": ObjectId(issue_id)})
    assert updated["status"] in ["resolved", "officer_review", "work_completed"]
    after_imgs = [img for img in updated.get("images", []) if img.get("type") == "after"]
    assert len(after_imgs) > 0
    assert "/files/resolution/" in after_imgs[0].get("url", "")

def test_worker_resolve_accepts_legacy_image(app_instance):
    """Verify backwards compatibility: worker can submit resolution proof using 'image' file field."""
    worker_id = str(ObjectId())
    db.users.insert_one({
        "_id": ObjectId(worker_id),
        "email": "worker2@smartcivic.local",
        "role": "worker",
        "ward": "Ward 1",
        "verified": True,
        "status": "APPROVED"
    })
    
    issue_id = str(ObjectId())
    db.issues.insert_one({
        "_id": ObjectId(issue_id),
        "title": "Streetlight off",
        "status": "in_progress",
        "worker_id": worker_id,
        "ward": "Ward 1"
    })

    with app_instance.app_context():
        worker_token, _ = generate_tokens(worker_id, "worker", "Ward 1")
    client_test = app_instance.test_client()
    client_test.set_cookie("access_token", worker_token)

    image_bytes = create_valid_jpeg()
    
    # Send using 'image'
    res = client_test.post(
        f"/api/issues/{issue_id}/resolve",
        data={
            "notes": "Replaced bulb",
            "image": (image_bytes, "bulb_replaced.jpg")
        },
        content_type="multipart/form-data"
    )

    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.get_json()}"
    data = res.get_json()
    assert data["success"] is True

def test_submit_resolution_dual_fields(app_instance):
    """Verify /api/issues/<id>/resolution route accepts after_image field."""
    worker_id = str(ObjectId())
    db.users.insert_one({
        "_id": ObjectId(worker_id),
        "email": "worker3@smartcivic.local",
        "role": "worker",
        "ward": "Ward 1",
        "verified": True,
        "status": "APPROVED"
    })

    issue_id = str(ObjectId())
    db.issues.insert_one({
        "_id": ObjectId(issue_id),
        "title": "Damaged bench",
        "status": "assigned",
        "worker_id": worker_id,
        "ward": "Ward 1"
    })

    with app_instance.app_context():
        worker_token, _ = generate_tokens(worker_id, "worker", "Ward 1")
    client_test = app_instance.test_client()
    client_test.set_cookie("access_token", worker_token)

    image_bytes = io.BytesIO(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb\x00C\x00\xff\xd9")

    res = client_test.post(
        f"/api/issues/{issue_id}/resolution",
        data={
            "notes": "Bench replaced",
            "after_image": (image_bytes, "bench.jpg")
        },
        content_type="multipart/form-data"
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
