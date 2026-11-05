"""
SmartCivic - Phase 3 Tests: Image Trust Gate
Tests blur, brightness, resolution, perceptual dHash duplicate checks,
EXIF stripping, and emergency override (Rule R8 / Exit Gate).
"""
import io
import os
import pytest
import numpy as np
import cv2
from PIL import Image

from app import create_app
from config import Config
from services.ai.image_gate import (
    evaluate_image_quality,
    compute_dhash,
    hamming_distance,
    compute_blur_score,
    compute_brightness_score,
    extract_exif_gps,
    store_image_hash
)
from utils.image_utils import save_image


@pytest.fixture
def app_instance():
    app = create_app()
    app.config["TESTING"] = True
    from app import limiter
    limiter.enabled = False
    return app


@pytest.fixture
def client(app_instance):
    return app_instance.test_client()


def _create_sharp_image(width=400, height=300):
    """Generates a sharp image with high-frequency checkerboard pattern."""
    arr = ((np.indices((height, width)).sum(axis=0) // 10) % 2) * 255
    arr = arr.astype(np.uint8)
    img = Image.fromarray(arr, mode='L').convert('RGB')
    buf = io.BytesIO()
    img.save(buf, format='JPEG')
    buf.seek(0)
    buf.filename = "sharp.jpg"
    return img, buf


def _create_blurred_image(width=400, height=300):
    """Generates a blurred low-variance image."""
    arr = ((np.indices((height, width)).sum(axis=0) // 10) % 2) * 255
    arr = arr.astype(np.uint8)
    blurred = cv2.GaussianBlur(arr, (45, 45), 0)
    img = Image.fromarray(blurred, mode='L').convert('RGB')
    buf = io.BytesIO()
    img.save(buf, format='JPEG')
    buf.seek(0)
    buf.filename = "blurred.jpg"
    return img, buf


def _create_dark_image(width=400, height=300):
    """Generates an underexposed dark image (mean brightness < 35)."""
    arr = np.full((height, width), 15, dtype=np.uint8)
    img = Image.fromarray(arr, mode='L').convert('RGB')
    buf = io.BytesIO()
    img.save(buf, format='JPEG')
    buf.seek(0)
    buf.filename = "dark.jpg"
    return img, buf


def _create_overexposed_image(width=400, height=300):
    """Generates a washed-out bright image (mean brightness > 235)."""
    arr = np.full((height, width), 245, dtype=np.uint8)
    img = Image.fromarray(arr, mode='L').convert('RGB')
    buf = io.BytesIO()
    img.save(buf, format='JPEG')
    buf.seek(0)
    buf.filename = "overexposed.jpg"
    return img, buf


def _create_small_image(width=150, height=120):
    """Generates an image below min resolution thresholds."""
    arr = np.full((height, width), 128, dtype=np.uint8)
    img = Image.fromarray(arr, mode='L').convert('RGB')
    buf = io.BytesIO()
    img.save(buf, format='JPEG')
    buf.seek(0)
    buf.filename = "small.jpg"
    return img, buf


def test_sharp_image_passes():
    """Verify that a sharp, well-lit image of adequate resolution passes all checks."""
    img, _ = _create_sharp_image(400, 300)
    res = evaluate_image_quality(img)
    envelope = res
    assert envelope["source"] == "rules"
    assert envelope["evidence_level"] == "detected"
    assert envelope["fallback_used"] is False

    val = envelope["value"]
    assert val["passed"] is True
    assert val["is_blurry"] is False
    assert val["is_dark"] is False
    assert val["is_overexposed"] is False
    assert val["is_too_small"] is False
    assert val["issues"] == []
    assert val["metrics"]["blur"] >= Config.IMAGE_GATE_BLUR_THRESHOLD


def test_blurred_image_detected():
    """Verify that a blurred image is flagged with is_blurry=True and passed=False."""
    img, _ = _create_blurred_image(400, 300)
    res = evaluate_image_quality(img)
    val = res["value"]
    assert val["passed"] is False
    assert val["is_blurry"] is True
    assert "blurry" in val["issues"]
    assert val["metrics"]["blur"] < Config.IMAGE_GATE_BLUR_THRESHOLD
    assert "blurry" in val["clarification_message"].lower()


def test_dark_image_detected():
    """Verify that an underexposed dark image is flagged with is_dark=True."""
    img, _ = _create_dark_image(400, 300)
    res = evaluate_image_quality(img)
    val = res["value"]
    assert val["passed"] is False
    assert val["is_dark"] is True
    assert "dark" in val["issues"]
    assert val["metrics"]["brightness"] < Config.IMAGE_GATE_DARK_THRESHOLD
    assert "dark" in val["clarification_message"].lower()


def test_overexposed_image_detected():
    """Verify that an overexposed bright image is flagged with is_overexposed=True."""
    img, _ = _create_overexposed_image(400, 300)
    res = evaluate_image_quality(img)
    val = res["value"]
    assert val["passed"] is False
    assert val["is_overexposed"] is True
    assert "overexposed" in val["issues"]
    assert val["metrics"]["brightness"] > Config.IMAGE_GATE_OVEREXPOSED_THRESHOLD


def test_resolution_check_detected():
    """Verify that an image below min width or height is flagged with is_too_small=True."""
    img, _ = _create_small_image(200, 150)
    res = evaluate_image_quality(img)
    val = res["value"]
    assert val["passed"] is False
    assert val["is_too_small"] is True
    assert "too_small" in val["issues"]


def test_dhash_and_reused_photo_detection():
    """Verify perceptual dHash computation and duplicate photo detection against db."""
    class MockDB:
        def __init__(self):
            self.docs = []
            self.image_hashes = self
        def find(self, *args, **kwargs):
            return self
        def limit(self, n):
            return self.docs
        def insert_one(self, doc):
            self.docs.append(doc)

    mock_db = MockDB()

    img, _ = _create_sharp_image(400, 300)
    dhash1 = compute_dhash(img)

    # Store initial photo hash under issue 101
    store_image_hash(mock_db, dhash1, issue_id="issue_101", user_id="user_A")

    # Evaluate identical photo submitted for issue 102
    res = evaluate_image_quality(img, issue_id="issue_102", user_id="user_B", db=mock_db)
    val = res["value"]
    assert val["is_duplicate_photo"] is True
    assert "duplicate_photo" in val["issues"]
    assert "issue_101" in val["reused_issue_ids"]

    # Same issue comparing with itself should NOT be flagged duplicate
    res_self = evaluate_image_quality(img, issue_id="issue_101", user_id="user_A", db=mock_db)
    assert res_self["value"]["is_duplicate_photo"] is False


def test_exif_gps_extraction_and_stripping(tmp_path):
    """Verify EXIF GPS extraction works and save_image strips all EXIF metadata."""
    img = Image.new('RGB', (400, 300), color=(120, 150, 180))
    exif = Image.Exif()
    gps_ifd = exif.get_ifd(0x8825)
    gps_ifd[1] = 'N'
    gps_ifd[2] = (12, 58, 23)
    gps_ifd[3] = 'E'
    gps_ifd[4] = (77, 35, 45)
    exif[0x8825] = gps_ifd

    img_buf = io.BytesIO()
    img.save(img_buf, format='JPEG', exif=exif)
    img_buf.seek(0)

    # 1. Test extraction
    coords = extract_exif_gps(img_buf)
    assert coords is not None
    assert abs(coords["latitude"] - 12.973) < 0.01
    assert abs(coords["longitude"] - 77.595) < 0.01

    # 2. Test stripping on disk persistence
    img_buf.seek(0)
    img_buf.filename = "test.jpg"
    saved_fname = save_image(img_buf, upload_dir=str(tmp_path))
    saved_path = os.path.join(str(tmp_path), saved_fname)
    
    saved_img = Image.open(saved_path)
    exif_after = saved_img.getexif()
    assert len(exif_after) == 0
    assert extract_exif_gps(saved_path) is None


def test_emergency_bypass_exit_gate(client, app_instance, monkeypatch):
    """
    Exit Gate Rule R8: Emergency submissions with low-quality photos NEVER get blocked.
    Non-emergency submissions with low-quality photos trigger CTVE.
    """
    from config import Config
    from bson import ObjectId
    from routes.auth import generate_tokens
    from app import db

    monkeypatch.setattr(Config, "AI_IMAGE_GATE_ENABLED", True)
    app_instance.config["AI_IMAGE_GATE_ENABLED"] = True

    with app_instance.app_context():
        import uuid
        user_id = ObjectId()
        unique_email = f"image_gate_{uuid.uuid4().hex[:8]}@test.invalid"
        db.users.insert_one({
            "_id": user_id,
            "email": unique_email,
            "role": "citizen",
            "verified": True,
            "verification_status": "approved",
            "status": "active",
            "ward": "Ward 1"
        })
        token, _ = generate_tokens(str(user_id), "citizen", "Ward 1")
        headers = {"Authorization": f"Bearer {token}"}

    _, blurred_buf = _create_blurred_image(400, 300)

    # 1. Non-emergency submission with blurred photo -> CTVE triggered
    non_emerg_data = {
        "title": "Minor pothole on residential road",
        "description": "A medium sized pothole has developed on the road near corner.",
        "category": "Roads",
        "image": (blurred_buf, "pothole.jpg")
    }
    resp1 = client.post('/api/issues', data=non_emerg_data, headers=headers, content_type='multipart/form-data')
    assert resp1.status_code == 201
    data1 = resp1.get_json()
    assert data1["success"] is True
    assert data1["ctve_triggered"] is True
    assert "blurry" in data1["ctve_message"].lower()
    assert data1["image_gate"]["is_blurry"] is True

    # 2. Emergency submission with blurred photo -> Emergency fast-lane, NOT blocked by CTVE
    _, blurred_buf2 = _create_blurred_image(400, 300)
    emerg_data = {
        "title": "Gas leak explosion risk fire imminent danger",
        "description": "LPG cylinder fire and gas leak spreading rapidly near homes, emergency help needed!",
        "category": "Emergency",
        "image": (blurred_buf2, "emergency.jpg")
    }
    resp2 = client.post('/api/issues', data=emerg_data, headers=headers, content_type='multipart/form-data')
    assert resp2.status_code == 201
    data2 = resp2.get_json()
    assert data2["success"] is True
    assert data2["priority"] == "P0"
    # Never block emergency submissions: CTVE must not gate an emergency
    assert data2["ctve_triggered"] is False
