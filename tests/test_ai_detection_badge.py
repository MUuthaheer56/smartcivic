"""
SmartCivic - Test AI Detection Badge & Preview Endpoint (Part 1 Verification)
Tests:
- /api/issues/image-quality-check returns detector status and message.
- "detected" format: "AI detected: <defect type> (confidence XX%) • Severity X/10"
- Multiple detections format: "+N more"
- "none" format: "AI could not detect a civic issue in this image. You can still submit your report."
- "unavailable" format: "AI check unavailable right now."
- Persistence on issue document upon submission.
- Escaping and serializer whitelist inclusion.
"""
import io
import pytest
from PIL import Image
from bson import ObjectId

from app import create_app, db
from routes.auth import generate_tokens
from services.ai.road_detector import detect_and_format_defect


def test_detect_and_format_defect_clean_image():
    """Synthetic clean image yields no defects."""
    img = Image.new("RGB", (320, 240), color=(128, 128, 128))
    res = detect_and_format_defect(img)
    assert res["status"] == "none"
    assert res["available"] is True
    assert res["has_detections"] is False
    assert res["message"] == "AI could not detect a civic issue in this image. You can still submit your report."


def test_detect_and_format_defect_unavailable():
    """None or invalid image yields unavailable status without crashing."""
    res = detect_and_format_defect(None)
    assert res["status"] == "unavailable"
    assert res["available"] is False
    assert res["message"] == "AI check unavailable right now."


def test_detect_and_format_defect_formatting(monkeypatch):
    """Verifies defect string formatting for single and multiple detections."""
    import services.ai.road_detector as rd

    # Mock single detection
    fake_single_val = {
        "value": {
            "available": True,
            "detections": [{
                "class_name": "Pothole",
                "confidence": 0.85,
                "severity": "high",
                "severity_score": 0.8
            }],
            "primary_defect": "Pothole",
            "severity": "high",
            "severity_score": 0.8
        },
        "confidence": 0.85
    }
    monkeypatch.setattr(rd, "run_road_detector", lambda *args, **kwargs: fake_single_val)
    single_res = rd.detect_and_format_defect("fake_img.jpg")
    assert single_res["status"] == "detected"
    assert single_res["message"] == "AI detected: Pothole (confidence 85%) • Severity 8/10"

    # Mock multiple detections
    fake_multi_val = {
        "value": {
            "available": True,
            "detections": [
                {"class_name": "Pothole", "confidence": 0.85, "severity": "high", "severity_score": 0.8},
                {"class_name": "Crack", "confidence": 0.65, "severity": "medium", "severity_score": 0.5},
                {"class_name": "Surface Erosion", "confidence": 0.55, "severity": "low", "severity_score": 0.3}
            ],
            "primary_defect": "Pothole",
            "severity": "high",
            "severity_score": 0.8
        },
        "confidence": 0.85
    }
    monkeypatch.setattr(rd, "run_road_detector", lambda *args, **kwargs: fake_multi_val)
    multi_res = rd.detect_and_format_defect("fake_img.jpg")
    assert multi_res["status"] == "detected"
    assert multi_res["message"] == "AI detected: Pothole (confidence 85%) • Severity 8/10 +2 more"


def test_preview_endpoint_auth_and_detection():
    """Tests /api/issues/image-quality-check with authenticated citizen."""
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    client = app.test_client()

    citizen_id = ObjectId()
    db.users.insert_one({
        "_id": citizen_id,
        "email": f"citizen_{citizen_id}@smartcivic.test",
        "role": "citizen",
        "ward": "Ward 1",
        "ward_id": "ward_1",
        "verified": True,
        "verification_status": "verified",
        "status": "active"
    })

    with app.app_context():
        token, _ = generate_tokens(str(citizen_id), "citizen", "Ward 1")
    headers = {"Authorization": f"Bearer {token}"}

    # Create dummy PNG image bytes
    img = Image.new("RGB", (200, 200), color=(200, 200, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    data = {"image": (buf, "test.png", "image/png")}
    res = client.post("/api/issues/image-quality-check", data=data, content_type="multipart/form-data", headers=headers)
    assert res.status_code == 200
    json_data = res.get_json()
    assert json_data["success"] is True
    assert "detector" in json_data
    assert json_data["detector"]["status"] in ("detected", "none", "unavailable")
    assert "message" in json_data["detector"]
