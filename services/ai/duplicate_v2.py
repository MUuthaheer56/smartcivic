"""
SmartCivic — Duplicate & Corroboration Detection v2 (Geo + Text Embeddings)
Finds similar civic complaints nearby using geospatial radius queries and multilingual
text embedding cosine similarity.
Outputs suggestions to db.duplicate_links. NEVER auto-merges or suppresses issues.
"""
from datetime import datetime
from typing import Dict, Any, List, Optional
from bson import ObjectId
import logging

from config import Config
from utils.geo_utils import haversine_distance
from services.ai.envelope import make_ai_result
from services.ai.embeddings import compute_text_embedding, cosine_similarity

logger = logging.getLogger(__name__)

SUGGESTION_THRESHOLD = 0.60

def get_or_compute_issue_embedding(db, issue_doc: dict) -> List[float]:
    """Retrieves cached embedding from issue document or computes & caches it in DB."""
    cached = issue_doc.get("text_embedding")
    if cached and isinstance(cached, list) and len(cached) > 0:
        return cached

    desc = issue_doc.get("translated_description") or issue_doc.get("description") or issue_doc.get("title") or ""
    emb = compute_text_embedding(desc)

    if db is not None and "_id" in issue_doc:
        try:
            db.issues.update_one({"_id": issue_doc["_id"]}, {"$set": {"text_embedding": emb}})
            issue_doc["text_embedding"] = emb
        except Exception as e:
            logger.debug(f"[DuplicateV2] Failed to cache embedding for issue {issue_doc['_id']}: {e}")

    return emb

def find_duplicate_candidates_v2(
    db,
    issue_id: Any,
    description: str,
    location: dict,
    category: str = None,
    ward: str = None
) -> Dict[str, Any]:
    """
    Candidate retrieval + embedding similarity scoring.
    Returns AI result envelope with duplicate suggestions and logs rows to db.duplicate_links.
    NEVER auto-merges.
    """
    if db is None:
        return make_ai_result(value={"duplicate_links": []}, confidence=0.0, source="embeddings")

    # Extract coordinates
    coords = location.get("coordinates") if isinstance(location, dict) else None
    if coords and len(coords) == 2:
        lng, lat = float(coords[0]), float(coords[1])
    else:
        lat = float(location.get("latitude") or location.get("lat", 0.0))
        lng = float(location.get("longitude") or location.get("lng", 0.0))

    radius_meters = getattr(Config, "DUPLICATE_RADIUS_METERS", 200)

    # 1. Geo candidate retrieval
    query_exclude = {"$ne": ObjectId(issue_id)} if (issue_id and ObjectId.is_valid(str(issue_id))) else {"$ne": issue_id}
    base_query = {
        "_id": query_exclude,
        "status": {"$nin": ["closed", "rejected"]}
    }
    if category and category.lower() != "other":
        base_query["category"] = category

    candidates = []
    if lat != 0.0 or lng != 0.0:
        try:
            geo_query = {
                **base_query,
                "location": {
                    "$near": {
                        "$geometry": {"type": "Point", "coordinates": [lng, lat]},
                        "$maxDistance": radius_meters
                    }
                }
            }
            candidates = list(db.issues.find(geo_query).limit(40))
        except Exception:
            candidates = []

    # Fallback if 2dsphere query returned empty or is not yet populated
    if not candidates and ward:
        candidates = list(db.issues.find({**base_query, "ward": ward}).sort("created_at", -1).limit(40))
    elif not candidates:
        candidates = list(db.issues.find(base_query).sort("created_at", -1).limit(40))

    new_emb = compute_text_embedding(description)
    suggestions = []
    top_score = 0.0

    for cand in candidates:
        c_loc = cand.get("location", {})
        c_coords = c_loc.get("coordinates") if isinstance(c_loc, dict) else None
        if c_coords and len(c_coords) == 2:
            c_lng, c_lat = float(c_coords[0]), float(c_coords[1])
        else:
            c_lat = float(cand.get("latitude") or 0.0)
            c_lng = float(cand.get("longitude") or 0.0)

        # Distance calculation
        dist_m = haversine_distance(lat, lng, c_lat, c_lng)
        if dist_m > radius_meters:
            continue

        cand_emb = get_or_compute_issue_embedding(db, cand)
        text_sim = cosine_similarity(new_emb, cand_emb)
        geo_score = max(0.0, 1.0 - (dist_m / max(radius_meters, 1)))

        # Weighted combination: 60% text similarity, 40% geospatial proximity
        score = (0.60 * text_sim) + (0.40 * geo_score)
        if dist_m <= 25.0:
            score = min(1.0, score + 0.10)

        cand_id_str = cand.get("issue_id") or str(cand["_id"])
        if score >= SUGGESTION_THRESHOLD:
            top_score = max(top_score, score)
            sugg_item = {
                "source_issue_id": str(issue_id),
                "candidate_issue_id": cand_id_str,
                "candidate_title": cand.get("title") or cand.get("description", "")[:60],
                "candidate_status": cand.get("status", "submitted"),
                "candidate_ward": cand.get("ward", ""),
                "score": round(score, 3),
                "text_similarity": round(text_sim, 3),
                "geo_score": round(geo_score, 3),
                "distance_meters": round(dist_m, 1),
                "status": "suggested"
            }
            suggestions.append(sugg_item)

            # Persist suggestion row in db.duplicate_links (upsert)
            try:
                db.duplicate_links.update_one(
                    {"source_issue_id": str(issue_id), "target_issue_id": cand_id_str},
                    {"$set": {
                        "source_issue_id": str(issue_id),
                        "target_issue_id": cand_id_str,
                        "score": round(score, 3),
                        "components": {
                            "text_similarity": round(text_sim, 3),
                            "geo_score": round(geo_score, 3),
                            "distance_meters": round(dist_m, 1)
                        },
                        "status": "suggested",
                        "updated_at": datetime.utcnow()
                    },
                    "$setOnInsert": {"created_at": datetime.utcnow()}},
                    upsert=True
                )
            except Exception as e:
                logger.debug(f"[DuplicateV2] Error upserting duplicate_link: {e}")

    suggestions.sort(key=lambda x: x["score"], reverse=True)

    envelope = make_ai_result(
        value={"duplicate_links": suggestions, "candidate_count": len(suggestions)},
        confidence=round(top_score, 3) if top_score > 0 else 0.0,
        source="embeddings",
        model_version="v2.0-geo-embed",
        evidence_level="inferred"
    )

    return envelope

