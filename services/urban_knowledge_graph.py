"""
SmartCivic v2 — Urban Knowledge Graph Service
Graph-Based Urban Knowledge Network correlation engine.
Identifies causal dependencies, constructs incident edges, and clusters related issues into Master Incidents.
"""

import math
from datetime import datetime, timedelta
from bson import ObjectId
import logging

logger = logging.getLogger(__name__)

def haversine_distance(coord1, coord2):
    """Calculates distance in meters between two [lng, lat] coordinates."""
    if not coord1 or not coord2:
        return float('inf')
    try:
        lng1, lat1 = float(coord1[0]), float(coord1[1])
        lng2, lat2 = float(coord2[0]), float(coord2[1])
        R = 6371000.0  # Earth radius in meters
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lng2 - lng1)
        a = math.sin(delta_phi / 2.0)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
        return R * c
    except (TypeError, ValueError, IndexError):
        return float('inf')

def _extract_coords(issue):
    """Helper to extract [lng, lat] from issue document."""
    loc = issue.get("location")
    if isinstance(loc, dict) and loc.get("type") == "Point" and isinstance(loc.get("coordinates"), list):
        return loc["coordinates"]
    lat = issue.get("latitude") or issue.get("lat")
    lng = issue.get("longitude") or issue.get("lng")
    if lat is not None and lng is not None:
        return [float(lng), float(lat)]
    return None

def evaluate_causal_rule(issue_a, issue_b, dist_m):
    """
    Evaluates correlation and causal relationships between two nearby issues.
    Returns (rule_name, weight, root_issue, dependent_issue) or None.
    """
    cat_a = (issue_a.get("category") or "").lower()
    cat_b = (issue_b.get("category") or "").lower()
    dept_a = (issue_a.get("department") or "").lower()
    dept_b = (issue_b.get("department") or "").lower()

    # Rule 1: Water leak / pipe burst causing road damage / pothole
    water_cats = {"water", "water_board", "pipeline", "leak", "water_supply"}
    road_cats = {"road", "roads", "pothole", "asphalt", "street"}
    drain_cats = {"drainage", "sewage", "overflow", "drain"}

    if (cat_a in water_cats or dept_a in water_cats) and (cat_b in road_cats or dept_b in road_cats or cat_b in drain_cats):
        if dist_m <= 250:
            return ("water_causes_road_damage", 0.85, issue_a, issue_b)
    elif (cat_b in water_cats or dept_b in water_cats) and (cat_a in road_cats or dept_a in road_cats or cat_a in drain_cats):
        if dist_m <= 250:
            return ("water_causes_road_damage", 0.85, issue_b, issue_a)

    # Rule 2: Drainage overflow causing road damage or water accumulation
    if (cat_a in drain_cats or dept_a in drain_cats) and (cat_b in road_cats or dept_b in road_cats):
        if dist_m <= 200:
            return ("drainage_overflow", 0.80, issue_a, issue_b)
    elif (cat_b in drain_cats or dept_b in drain_cats) and (cat_a in road_cats or dept_a in road_cats):
        if dist_m <= 200:
            return ("drainage_overflow", 0.80, issue_b, issue_a)

    # Rule 3: Same category spatial proximity
    if cat_a == cat_b and cat_a != "":
        if dist_m <= 150:
            # Earliest created issue is root
            created_a = issue_a.get("created_at") or datetime.utcnow()
            created_b = issue_b.get("created_at") or datetime.utcnow()
            root = issue_a if created_a <= created_b else issue_b
            dep = issue_b if created_a <= created_b else issue_a
            return ("spatial_proximity", 0.60, root, dep)

    # Rule 4: General spatial proximity (within 100m)
    if dist_m <= 100:
        created_a = issue_a.get("created_at") or datetime.utcnow()
        created_b = issue_b.get("created_at") or datetime.utcnow()
        root = issue_a if created_a <= created_b else issue_b
        dep = issue_b if created_a <= created_b else issue_a
        return ("cross_dept_correlation", 0.50, root, dep)

    return None

def analyze_correlations(db, issue_id):
    """
    Analyzes spatial and domain correlations for a given issue.
    Constructs incident edges, links issues to Master Incidents, and updates roles.
    """
    if isinstance(issue_id, str):
        try:
            issue_id = ObjectId(issue_id)
        except Exception:
            return None

    target = db.issues.find_one({"_id": issue_id})
    if not target:
        return None

    target_coords = _extract_coords(target)
    if not target_coords:
        return {
            "changed": False,
            "master_id": target.get("master_incident_id"),
            "root_id": target.get("_id"),
            "member_ids": [target.get("_id")]
        }

    # Find candidates nearby (bounding box or scan recent non-closed issues)
    query = {
        "_id": {"$ne": issue_id},
        "status": {"$ne": "closed"}
    }
    if target.get("test_tag"):
        query["test_tag"] = target["test_tag"]

    candidates = list(db.issues.find(query))
    
    correlated_edges = []
    connected_issue_map = {target["_id"]: target}

    for candidate in candidates:
        cand_coords = _extract_coords(candidate)
        if not cand_coords:
            continue
        dist = haversine_distance(target_coords, cand_coords)
        if dist > 500:
            continue

        res = evaluate_causal_rule(target, candidate, dist)
        if res:
            rule_name, weight, root_issue, dep_issue = res
            correlated_edges.append({
                "rule": rule_name,
                "weight": weight,
                "root": root_issue,
                "dep": dep_issue
            })
            connected_issue_map[candidate["_id"]] = candidate

    if not correlated_edges:
        existing_master_id = target.get("master_incident_id")
        return {
            "changed": False,
            "master_id": existing_master_id,
            "root_id": target.get("_id"),
            "member_ids": [target["_id"]]
        }

    # Determine overall root cause among all connected issues
    all_members = list(connected_issue_map.values())
    
    # Priority for root cause: Water/Drainage > Earliest created
    water_roots = [
        m for m in all_members 
        if (m.get("category") or "").lower() in {"water", "water_board", "pipeline", "leak", "drainage", "sewage"}
        or (m.get("department") or "").lower() in {"water", "water_board", "pipeline", "leak", "drainage", "sewage"}
    ]
    
    if water_roots:
        root_doc = min(water_roots, key=lambda x: x.get("created_at") or datetime.utcnow())
    else:
        root_doc = min(all_members, key=lambda x: x.get("created_at") or datetime.utcnow())

    root_id = root_doc["_id"]
    member_ids = list(connected_issue_map.keys())

    # Write incident edges
    now = datetime.utcnow()
    for edge in correlated_edges:
        f_id = edge["root"]["_id"]
        t_id = edge["dep"]["_id"]
        db.incident_edges.update_one(
            {"from_id": f_id, "to_id": t_id, "rule": edge["rule"]},
            {
                "$set": {
                    "from_id": f_id,
                    "to_id": t_id,
                    "rule": edge["rule"],
                    "weight": edge["weight"],
                    "updated_at": now
                },
                "$setOnInsert": {
                    "created_at": now
                }
            },
            upsert=True
        )

    # Master Incident logic
    existing_master_ids = set()
    for m_doc in all_members:
        if m_doc.get("master_incident_id"):
            existing_master_ids.add(m_doc["master_incident_id"])

    departments = list(set([m.get("department") for m in all_members if m.get("department")]))
    categories = list(set([m.get("category") for m in all_members if m.get("category")]))
    confidence = max([e["weight"] for e in correlated_edges]) if correlated_edges else 0.50

    if existing_master_ids:
        master_id = list(existing_master_ids)[0]
        m_curr = db.master_incidents.find_one({"_id": master_id})
        current_members = set(m_curr.get("member_ids", [])) if m_curr else set()
        merged_members = list(current_members.union(set(member_ids)))

        db.master_incidents.update_one(
            {"_id": master_id},
            {
                "$set": {
                    "root_issue_id": root_id,
                    "member_ids": merged_members,
                    "departments": departments,
                    "categories": categories,
                    "confidence": confidence,
                    "status": "active",
                    "updated_at": now
                }
            }
        )
        final_member_ids = merged_members
    else:
        master_doc = {
            "root_issue_id": root_id,
            "member_ids": member_ids,
            "status": "active",
            "departments": departments,
            "categories": categories,
            "confidence": confidence,
            "created_at": now,
            "updated_at": now
        }
        master_id = db.master_incidents.insert_one(master_doc).inserted_id
        final_member_ids = member_ids

    # Update issue documents with master_incident_id and cluster_role
    for m_id in final_member_ids:
        role = "root" if m_id == root_id else "member"
        db.issues.update_one(
            {"_id": m_id},
            {
                "$set": {
                    "master_incident_id": master_id,
                    "cluster_role": role
                }
            }
        )

    return {
        "changed": True,
        "master_id": master_id,
        "root_id": root_id,
        "member_ids": final_member_ids
    }
