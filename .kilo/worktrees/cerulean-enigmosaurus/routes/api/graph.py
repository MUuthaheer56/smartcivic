"""
SmartCivic v2 — Graph API Blueprint
Exposes graph visualization endpoints for officers to inspect causal incident clusters.
"""

from flask import Blueprint, jsonify, abort
from bson import ObjectId
from bson.errors import InvalidId
from models.user import get_db
from utils.auth_helpers import officer_required

graph_bp = Blueprint("graph_api", __name__, url_prefix="/api")

def _oid(s):
    try:
        return ObjectId(s)
    except (InvalidId, TypeError):
        return None

def _node(d):
    loc = d.get("location")
    if isinstance(loc, dict) and "coordinates" in loc and isinstance(loc["coordinates"], list):
        lat = loc["coordinates"][1]
        lng = loc["coordinates"][0]
    else:
        lat = float(d.get("latitude") or d.get("lat") or 0.0)
        lng = float(d.get("longitude") or d.get("lng") or 0.0)

    cat = d.get("category") or (d.get("ai_analysis") or {}).get("category") or "General"
    return {
        "id": str(d["_id"]),
        "category": cat,
        "status": d.get("status", "submitted"),
        "department": d.get("department", "Unassigned"),
        "role": d.get("cluster_role", "standalone"),
        "lat": lat,
        "lng": lng
    }

@graph_bp.route("/issues/<issue_id>/graph", methods=["GET"])
@officer_required
def issue_graph(issue_id):
    db = get_db()
    oid = _oid(issue_id)
    query = {"$or": [{"_id": oid}, {"issue_id": issue_id}]} if oid else {"issue_id": issue_id}
    issue = db.issues.find_one(query)
    
    if not issue:
        abort(404)
        
    master_id = issue.get("master_incident_id")
    if not master_id:
        return jsonify(nodes=[_node(issue)], edges=[], master=None)
    
    if isinstance(master_id, str):
        master_id = _oid(master_id)
        
    m = db.master_incidents.find_one({"_id": master_id})
    if not m:
        return jsonify(nodes=[_node(issue)], edges=[], master=None)
        
    member_ids = m.get("member_ids", [])
    nodes = [_node(d) for d in db.issues.find({"_id": {"$in": member_ids}})]
    edges = [
        {
            "from": str(e["from_id"]),
            "to": str(e["to_id"]),
            "rule": e.get("rule", "correlated"),
            "weight": e.get("weight", 0.5)
        }
        for e in db.incident_edges.find({
            "from_id": {"$in": member_ids},
            "to_id": {"$in": member_ids}
        })
    ]
    return jsonify(
        nodes=nodes,
        edges=edges,
        master={
            "id": str(m["_id"]),
            "root": str(m.get("root_issue_id")),
            "departments": m.get("departments", []),
            "confidence": m.get("confidence", 0.5)
        }
    )

@graph_bp.route("/clusters/master", methods=["GET"])
@officer_required
def master_clusters():
    db = get_db()
    out = []
    for m in db.master_incidents.find({"status": "active"}).sort("updated_at", -1).limit(100):
        root_id = m.get("root_issue_id")
        if isinstance(root_id, str):
            root_id = _oid(root_id)
            
        root = db.issues.find_one({"_id": root_id})
        if not root:
            continue
            
        loc = root.get("location")
        if isinstance(loc, dict) and "coordinates" in loc and isinstance(loc["coordinates"], list):
            lat = loc["coordinates"][1]
            lng = loc["coordinates"][0]
        else:
            lat = float(root.get("latitude") or 0.0)
            lng = float(root.get("longitude") or 0.0)
            
        out.append({
            "id": str(m["_id"]),
            "root_id": str(m.get("root_issue_id")),
            "size": len(m.get("member_ids", [])),
            "departments": m.get("departments", []),
            "categories": m.get("categories", []),
            "confidence": m.get("confidence", 0.5),
            "lat": lat,
            "lng": lng
        })
    return jsonify(clusters=out)
