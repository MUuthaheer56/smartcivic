"""
Phase 2 — Duplicate & Corroboration v2 Verification Tests
Tests embeddings, candidate retrieval, weighted scoring, duplicate_links suggestions,
one-tap support API, and eval_duplicates.py report generation.
"""
import os
import csv
import tempfile
import pytest
from bson import ObjectId
from app import create_app, db
from config import Config
from routes.auth import generate_tokens
from services.ai.embeddings import compute_text_embedding, cosine_similarity
from services.ai.duplicate_v2 import find_duplicate_candidates_v2
from ml.evaluate.eval_duplicates import evaluate_duplicate_pairs

@pytest.fixture
def app_instance():
    app = create_app()
    app.config["TESTING"] = True
    from app import limiter
    limiter.enabled = False
    return app

@pytest.fixture
def test_client(app_instance):
    return app_instance.test_client()

def test_embeddings_and_cosine_similarity():
    """Validates vector dimensions and similarity bounds."""
    emb1 = compute_text_embedding("Huge pothole on 100ft road near junction")
    emb2 = compute_text_embedding("Deep pothole damaging cars on 100ft road")
    emb3 = compute_text_embedding("Streetlight flickering at night in park")

    assert len(emb1) == 512
    assert len(emb2) == 512
    assert len(emb3) == 512

    sim_potholes = cosine_similarity(emb1, emb2)
    sim_unrelated = cosine_similarity(emb1, emb3)

    assert sim_potholes > sim_unrelated
    assert sim_potholes >= 0.50

def test_duplicate_v2_candidate_scoring_and_suggestion(app_instance):
    """Confirms candidate scoring and persistence into db.duplicate_links without auto-merge."""
    with app_instance.app_context():
        cand_id = ObjectId()
        # Seed an existing complaint nearby
        db.issues.insert_one({
            "_id": cand_id,
            "issue_id": f"SC-EXISTING-{cand_id}",
            "title": "Severe road damage",
            "description": "Large dangerous pothole on MG Road near signal",
            "category": "road",
            "status": "under_review",
            "ward": "Ward 1",
            "location": {"type": "Point", "coordinates": [77.5946, 12.9716]},
            "latitude": 12.9716,
            "longitude": 77.5946,
            "support_count": 2,
            "supporters": []
        })

        new_issue_id = f"SC-NEW-{ObjectId()}"
        env = find_duplicate_candidates_v2(
            db=db,
            issue_id=new_issue_id,
            description="Deep pothole on MG road near traffic light causing accidents",
            location={"type": "Point", "coordinates": [77.5948, 12.9717]}, # ~25 meters away
            category="road",
            ward="Ward 1"
        )

        assert env["source"] == "embeddings"
        assert env["model_version"] == "v2.0-geo-embed"
        assert env["evidence_level"] == "inferred"

        links = env["value"]["duplicate_links"]
        assert len(links) >= 1
        top_match = links[0]
        assert top_match["score"] >= 0.60
        assert "text_similarity" in top_match
        assert "geo_score" in top_match
        assert top_match["distance_meters"] < 50.0

        # Verify suggestion stored in db.duplicate_links
        stored_link = db.duplicate_links.find_one({"source_issue_id": new_issue_id})
        assert stored_link is not None
        assert stored_link["status"] == "suggested"

        # Cleanup
        db.issues.delete_one({"_id": cand_id})
        db.duplicate_links.delete_many({"source_issue_id": new_issue_id})

def test_duplicate_suggestions_and_confirm_routes(test_client, app_instance):
    """Tests GET /api/issues/<id>/duplicate-suggestions and POST /api/issues/<id>/duplicate-confirm."""
    with app_instance.app_context():
        db.users.delete_many({"email": "phase2_citizen@test.invalid"})
        user_id = ObjectId()
        db.users.insert_one({
            "_id": user_id,
            "email": "phase2_citizen@test.invalid",
            "role": "citizen",
            "verified": True,
            "status": "active"
        })
        token, _ = generate_tokens(str(user_id), "citizen", "Ward 1")
        headers = {"Authorization": f"Bearer {token}"}

        target_id = ObjectId()
        db.issues.insert_one({
            "_id": target_id,
            "issue_id": f"SC-TARGET-{target_id}",
            "title": "Water pipeline burst",
            "description": "Water overflowing onto road",
            "category": "water",
            "status": "under_review",
            "support_count": 1,
            "supporters": []
        })

        source_id = ObjectId()
        db.issues.insert_one({
            "_id": source_id,
            "issue_id": f"SC-SOURCE-{source_id}",
            "title": "Water leakage nearby",
            "description": "Water overflowing from pipe",
            "category": "water",
            "status": "submitted"
        })

        # Insert a suggestion
        db.duplicate_links.insert_one({
            "source_issue_id": f"SC-SOURCE-{source_id}",
            "target_issue_id": f"SC-TARGET-{target_id}",
            "score": 0.85,
            "components": {"text_similarity": 0.9, "geo_score": 0.8, "distance_meters": 30.0},
            "status": "suggested"
        })

        # 1. GET suggestions
        res = test_client.get(f"/api/issues/SC-SOURCE-{source_id}/duplicate-suggestions", headers=headers)
        assert res.status_code == 200
        data = res.get_json()
        assert data["success"] is True
        assert len(data["suggestions"]) >= 1
        assert "Similar report nearby" in data["prompt"]

        # 2. POST confirm
        conf_res = test_client.post(
            f"/api/issues/SC-SOURCE-{source_id}/duplicate-confirm",
            headers=headers,
            json={"target_issue_id": f"SC-TARGET-{target_id}", "action": "confirm"}
        )
        assert conf_res.status_code == 200
        conf_data = conf_res.get_json()
        assert conf_data["status"] == "confirmed"

        # Check target issue received support
        updated_target = db.issues.find_one({"_id": target_id})
        assert updated_target["support_count"] == 2
        assert any(str(s.get("user_id")) == str(user_id) for s in updated_target["supporters"])

        # Check duplicate link marked confirmed
        link = db.duplicate_links.find_one({"source_issue_id": f"SC-SOURCE-{source_id}"})
        assert link["status"] == "confirmed"
        assert link["confirmed_by"] == str(user_id)

        # Check ai_corrections logged
        corr = db.ai_corrections.find_one({"issue_id": f"SC-SOURCE-{source_id}", "field_changed": "duplicate_link"})
        assert corr is not None
        assert corr["after_value"] == "confirmed"

        # Cleanup
        db.users.delete_one({"_id": user_id})
        db.issues.delete_one({"_id": target_id})
        db.issues.delete_one({"_id": source_id})
        db.duplicate_links.delete_many({"source_issue_id": f"SC-SOURCE-{source_id}"})
        db.ai_corrections.delete_many({"issue_id": f"SC-SOURCE-{source_id}"})

def test_eval_duplicates_report_generation():
    """Tests evaluation script on a small labelled pairs set."""
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="", encoding="utf-8") as tf:
        writer = csv.writer(tf)
        writer.writerow(["issue_a", "issue_b", "text_a", "text_b", "distance_meters", "is_duplicate", "label_source", "notes"])
        writer.writerow(["I1", "I2", "Dangerous pothole on road", "Deep pothole causing vehicle damage", 30.0, 1, "human", "positive match"])
        writer.writerow(["I1", "I3", "Dangerous pothole on road", "Streetlight not working on street", 25.0, 0, "human", "same loc diff problem"])
        writer.writerow(["I4", "I5", "Garbage pile on corner", "Trash dumping outside gate", 50.0, 1, "human", "positive match"])
        writer.writerow(["I4", "I6", "Garbage pile on corner", "Water leak on pipe", 500.0, 0, "human", "diff loc diff problem"])
        tf.flush()
        temp_csv = tf.name

    try:
        report_dir = tempfile.mkdtemp()
        eval_result = evaluate_duplicate_pairs(temp_csv, output_dir=report_dir)
        assert eval_result["sample_count"] == 4
        assert "metrics" in eval_result
        metrics = eval_result["metrics"]
        assert "keyword_match" in metrics
        assert "geo_only" in metrics
        assert "text_only" in metrics
        assert "text_plus_geo" in metrics
        assert os.path.exists(eval_result["report_path"])
    finally:
        if os.path.exists(temp_csv):
            os.remove(temp_csv)

