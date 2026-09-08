"""
SmartCivic — Duplicate Detection Service
Scans spatial proximity and semantic issue features to detect duplicate complaints.
"""
from config import Config
from app import db
from utils.geo_utils import haversine_distance
from bson import ObjectId

def find_duplicate_candidates(location: dict, prediction: dict) -> list:
    category = prediction.get("category", "other")
    
    # Query non-closed issues matching same category
    candidates = list(db.issues.find({
        "category": category,
        "status": {"$nin": ["closed", "rejected", "duplicate"]}
    }))
    
    nearby = []
    loc_lat = location.get("latitude") if "latitude" in location else location.get("lat")
    loc_lng = location.get("longitude") if "longitude" in location else location.get("lng")
    
    if loc_lat is None or loc_lng is None:
        coords = location.get("coordinates", [0, 0])
        loc_lng, loc_lat = coords[0], coords[1]
        
    for cand in candidates:
        cand_loc = cand.get("location", {})
        cand_coords = cand_loc.get("coordinates")
        if cand_coords and len(cand_coords) == 2:
            c_lng, c_lat = cand_coords[0], cand_coords[1]
        else:
            c_lat = cand_loc.get("latitude") or cand_loc.get("lat", 0)
            c_lng = cand_loc.get("longitude") or cand_loc.get("lng", 0)
            
        dist = haversine_distance(float(loc_lat), float(loc_lng), float(c_lat), float(c_lng))
        if dist <= Config.DUPLICATE_RADIUS_METERS:
            cand["distance_meters"] = dist
            nearby.append(cand)
            
    return nearby

def calculate_similarity(issue_a: dict, issue_b: dict) -> float:
    # Category match
    cat_a = str(issue_a.get("category", "")).lower()
    cat_b = str(issue_b.get("category", "")).lower()
    if cat_a != cat_b:
        return 0.0
        
    score = 0.5 # Same category within 200m radius gives baseline 0.5 similarity
    
    type_a = str(issue_a.get("type") or issue_a.get("issue_type", "")).lower()
    type_b = str(issue_b.get("type") or issue_b.get("issue_type", "")).lower()
    if type_a and type_b and (type_a in type_b or type_b in type_a):
        score += 0.35
        
    sev_a = str(issue_a.get("severity", "")).lower()
    sev_b = str(issue_b.get("severity", "")).lower()
    if sev_a == sev_b:
        score += 0.15
        
    return min(1.0, score)

def detect_duplicate(location: dict, prediction: dict) -> dict:
    candidates = find_duplicate_candidates(location, prediction)
    for candidate in candidates:
        sim = calculate_similarity({"location": location, **prediction}, candidate)
        if sim >= Config.DUPLICATE_THRESHOLD:
            cand_id = str(candidate.get("issue_id") or candidate["_id"])
            return {
                "is_duplicate": True,
                "matched_issue_id": cand_id,
                "similarity": round(sim, 2)
            }
    return {
        "is_duplicate": False,
        "matched_issue_id": None,
        "similarity": None
    }

def link_duplicate(new_issue_id: str, matched_issue_id: str) -> None:
    try:
        new_obj = ObjectId(new_issue_id)
        matched_obj = ObjectId(matched_issue_id)
    except Exception:
        return
        
    db.issues.update_one(
        {"_id": new_obj},
        {"$set": {
            "status": "duplicate",
            "duplicate_of": matched_obj,
            "duplicate.is_duplicate": True,
            "duplicate.matched_issue_id": matched_issue_id
        }}
    )
    db.issues.update_one(
        {"_id": matched_obj},
        {"$addToSet": {"duplicate_children": new_obj}, "$inc": {"duplicate_count": 1}}
    )
