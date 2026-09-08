"""
SmartCivic+ — Real Vision Test Runner
Executes actual Gemini Vision API call on real fixture image, tests fusion logic under multiple text prompts,
and tests the complete end-to-end API pipeline and MongoDB persistence.
"""
import os
import sys
import json
import io
import time
from datetime import datetime

# Set working directory to project root
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__)))
sys.path.insert(0, ROOT_DIR)

# Ensure environment variables from .env are loaded if python-dotenv is present or file exists
if os.path.exists(".env"):
    try:
        with open(".env", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    if k.strip() and not os.getenv(k.strip()):
                        os.environ[k.strip()] = v.strip().strip('"').strip("'")
    except Exception as e:
        print("Dotenv read warning:", e)

from app import create_app, db
from services import ai_service, assignment_service, complaint_service
from routes.auth import generate_tokens, hash_password
from bson import ObjectId

def run_real_vision_test():
    print("=" * 60)
    print("      SMARTCIVIC REAL GEMINI VISION TEST EXECUTION     ")
    print("=" * 60)

    # 1. Verification of environment & setup
    fixture_path = "tests/fixtures/dangerous-damaged-highway-after-heavy-rain.webp"
    fixture_exists = os.path.exists(fixture_path)
    api_key = os.getenv("GEMINI_API_KEY")
    api_configured = bool(api_key and len(api_key.strip()) > 5)
    
    import google.generativeai as genai
    sdk_version = getattr(genai, '__version__', 'unknown')
    vision_model_name = os.getenv("GEMINI_VISION_MODEL", "gemini-1.5-flash")

    print(f"Fixture path:       {fixture_path}")
    print(f"Fixture exists:     {fixture_exists}")
    print(f"API Key configured: {api_configured}")
    print(f"Vision Model:       {vision_model_name}")
    print(f"SDK Version:        {sdk_version}")

    if not fixture_exists:
        print("ERROR: Fixture image not found!")
        sys.exit(1)

    if not api_configured:
        print("ERROR: GEMINI_API_KEY is not configured!")
        sys.exit(1)

    # 2. Execute actual Gemini Vision inference on the test image
    print("\nExecuting real Gemini Vision inference on fixture image...")
    t0 = time.time()
    img_pred = ai_service.analyze_complaint_image(fixture_path)
    duration = round(time.time() - t0, 2)
    print(f"Inference completed in {duration}s")
    print("\nRAW GEMINI VISION OUTPUT:")
    print(json.dumps(img_pred, indent=2, default=str))

    # 3. Test Scenarios A, B, and C
    desc_a = "There is major damage to the highway road surface. The damaged section appears to create a serious hazard for vehicles."
    desc_b = "Please fix this issue."
    desc_c = "There is a water problem here."

    print("\nWaiting 25s to stay within Gemini API rate limits...")
    time.sleep(25)

    print("\n" + "=" * 60)
    print(" SCENARIO A: Image + Detailed Road-Damage Description")
    print("=" * 60)
    text_a = ai_service.analyze_complaint_text(desc_a)
    fusion_a = ai_service.fuse_complaint_predictions(text_a, img_pred)
    print("IMAGE PREDICTION:", json.dumps({k: img_pred.get(k) for k in ["category", "issue_type", "severity", "confidence", "reason"]}, indent=2))
    print("TEXT PREDICTION: ", json.dumps({k: text_a.get(k) for k in ["category", "type", "severity", "confidence", "provider"]}, indent=2))
    print("FUSION PREDICTION:", json.dumps({k: fusion_a.get(k) for k in ["category", "issue_type", "severity", "confidence", "reason", "prediction_disagreement"]}, indent=2))

    print("\nWaiting 25s to stay within Gemini API rate limits...")
    time.sleep(25)

    print("\n" + "=" * 60)
    print(" SCENARIO B: Image + Vague Description")
    print("=" * 60)
    text_b = ai_service.analyze_complaint_text(desc_b)
    fusion_b = ai_service.fuse_complaint_predictions(text_b, img_pred)
    print("IMAGE PREDICTION:", json.dumps({k: img_pred.get(k) for k in ["category", "issue_type", "severity", "confidence", "reason"]}, indent=2))
    print("TEXT PREDICTION: ", json.dumps({k: text_b.get(k) for k in ["category", "type", "severity", "confidence", "provider"]}, indent=2))
    print("FUSION PREDICTION:", json.dumps({k: fusion_b.get(k) for k in ["category", "issue_type", "severity", "confidence", "reason", "prediction_disagreement"]}, indent=2))

    print("\nWaiting 25s to stay within Gemini API rate limits...")
    time.sleep(25)

    print("\n" + "=" * 60)
    print(" SCENARIO C: Image + Misleading Description")
    print("=" * 60)
    text_c = ai_service.analyze_complaint_text(desc_c)
    fusion_c = ai_service.fuse_complaint_predictions(text_c, img_pred)
    print("IMAGE PREDICTION:", json.dumps({k: img_pred.get(k) for k in ["category", "issue_type", "severity", "confidence", "reason"]}, indent=2))
    print("TEXT PREDICTION: ", json.dumps({k: text_c.get(k) for k in ["category", "type", "severity", "confidence", "provider"]}, indent=2))
    print("FUSION PREDICTION:", json.dumps({k: fusion_c.get(k) for k in ["category", "issue_type", "severity", "confidence", "reason", "prediction_disagreement"]}, indent=2))

    print("\nWaiting 25s before API test to stay within rate limits...")
    time.sleep(25)

    # 4. End-to-End API Flow with Real Image Upload
    print("\n" + "=" * 60)
    print(" END-TO-END PIPELINE & PERSISTENCE VERIFICATION ")
    print("=" * 60)

    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()

    # Create temporary users for testing
    pwd_hash = hash_password("smartcivic123")
    citizen_id = ObjectId()
    worker_id = ObjectId()
    officer_id = ObjectId()

    db.users.insert_one({
        "_id": citizen_id,
        "name": "Vision Test Citizen",
        "email": "vision_citizen@smartcivic.com",
        "password_hash": pwd_hash,
        "role": "citizen",
        "ward": "Ward 1",
        "reputation_score": 50,
        "created_at": datetime.utcnow()
    })
    db.users.insert_one({
        "_id": worker_id,
        "name": "Vision Test Worker",
        "email": "vision_worker@smartcivic.com",
        "password_hash": pwd_hash,
        "role": "worker",
        "ward": "Ward 1",
        "skills": ["road_repair", "roads", "road"],
        "is_available": True,
        "active_assignments": 0,
        "created_at": datetime.utcnow()
    })
    db.users.insert_one({
        "_id": officer_id,
        "name": "Vision Test Officer",
        "email": "vision_officer@smartcivic.com",
        "password_hash": pwd_hash,
        "role": "officer",
        "ward": "all",
        "created_at": datetime.utcnow()
    })

    with app.app_context():
        citizen_token, _ = generate_tokens(str(citizen_id), "citizen", "Ward 1")
        officer_token, _ = generate_tokens(str(officer_id), "officer", "all")
        worker_token, _ = generate_tokens(str(worker_id), "worker", "Ward 1")

    # Step A: POST /api/issues with actual webp image binary stream
    client.set_cookie('access_token', citizen_token)
    with open(fixture_path, "rb") as f_img:
        img_bytes = f_img.read()
    
    data_payload = {
        "title": "Damaged Highway Surface After Heavy Rain",
        "description": desc_a,
        "category": "road",
        "type": "pothole",
        "lat": "12.9716",
        "lng": "77.5946",
        "address": "NH Highway, Ward 1",
        "ward": "Ward 1",
        "image": (io.BytesIO(img_bytes), "dangerous-damaged-highway-after-heavy-rain.webp")
    }
    res = client.post('/api/issues', data=data_payload, content_type='multipart/form-data')
    
    print(f"POST /api/issues status code: {res.status_code}")
    res_json = res.get_json()
    if not res_json.get("success"):
        print("API Submission failed:", res_json)
        sys.exit(1)

    issue_id_str = res_json["data"]["_id"]
    issue_id_obj = ObjectId(issue_id_str)
    print(f"Created Issue ID: {issue_id_str}")

    # Step B: MongoDB persistence check
    db_issue = db.issues.find_one({"_id": issue_id_obj})
    print("\nMongoDB Saved Document Verification:")
    print(" - Has 'image_analysis':", "image_analysis" in db_issue)
    print(" - Has 'text_analysis': ", "text_analysis" in db_issue)
    print(" - Has 'ai_analysis':   ", "ai_analysis" in db_issue)
    print(" - Image Provider:     ", db_issue.get("image_analysis", {}).get("provider"))
    print(" - Image Available:    ", db_issue.get("image_analysis", {}).get("available"))
    print(" - Detected Category:  ", db_issue.get("category"))
    print(" - Detected Severity:  ", db_issue.get("severity"))
    print(" - Assigned Department:", db_issue.get("department"))

    # Step C: Citizen dashboard check
    res_citizen = client.get('/api/issues')
    print("Citizen Dashboard GET /api/issues status:", res_citizen.status_code)
    citizen_issues = res_citizen.get_json().get("data", [])
    found_citizen = any(i["_id"] == issue_id_str for i in citizen_issues)
    print(" - Issue visible in Citizen Dashboard:", found_citizen)

    # Step D: Officer dashboard check & worker assignment
    client.set_cookie('access_token', officer_token)
    res_officer_overview = client.get('/api/analytics/overview')
    print("Officer Dashboard Overview status:", res_officer_overview.status_code)

    res_assign = client.post(f'/api/issues/{issue_id_str}/assign', json={"worker_id": str(worker_id)})
    print("Officer Worker Assignment status:", res_assign.status_code)
    db_issue_after_assign = db.issues.find_one({"_id": issue_id_obj})
    print(" - Issue status after assignment:", db_issue_after_assign.get("status"))
    print(" - Assigned worker_id:           ", str(db_issue_after_assign.get("worker_id")))

    # Step E: Officer Override Test (Verify original AI prediction remains intact)
    res_override = client.post(f'/api/issues/{issue_id_str}/review', json={
        "category": "road",
        "severity": "critical",
        "department": "roads",
        "reason": "Officer manually escalated to critical severity"
    })
    print("Officer Review Override status:", res_override.status_code)
    db_issue_after_override = db.issues.find_one({"_id": issue_id_obj})
    print(" - Original AI Analysis intact: ", "ai_analysis" in db_issue_after_override)
    print(" - Original Image Analysis intact:", "image_analysis" in db_issue_after_override and db_issue_after_override.get("image_analysis", {}).get("available") is True)
    print(" - Officer Override saved:      ", db_issue_after_override.get("ai_analysis", {}).get("officer_overridden") is True)

    # Cleanup temp users and issue
    db.users.delete_one({"_id": citizen_id})
    db.users.delete_one({"_id": worker_id})
    db.users.delete_one({"_id": officer_id})
    db.issues.delete_one({"_id": issue_id_obj})

    return {
        "img_pred": img_pred,
        "fusion_a": fusion_a,
        "text_a": text_a
    }

if __name__ == '__main__':
    run_real_vision_test()
