# db.routes schema representation:
# {
#   _id: ObjectId,
#   worker_id: ObjectId,
#   community_id: ObjectId,
#   issue_ids: [ObjectId],
#   optimized_order: [str],
#   waypoints: [{
#     issue_id: str,
#     lat: float,
#     lng: float,
#     sequence: int,
#     title: str,
#     severity: int,
#     category: str,
#     address: str
#   }],
#   total_distance_km: float,
#   estimated_duration_min: int,
#   status: str("active"|"completed"),
#   created_at: datetime,
#   completed_at: datetime|None
# }

def create_route_doc(worker_id, community_id, issue_ids, optimized_order, waypoints, total_distance_km, estimated_duration_min):
    from datetime import datetime
    from bson import ObjectId
    return {
        "worker_id": ObjectId(worker_id),
        "community_id": ObjectId(community_id),
        "issue_ids": [ObjectId(iid) for iid in issue_ids],
        "optimized_order": optimized_order,
        "waypoints": waypoints,
        "total_distance_km": float(total_distance_km),
        "estimated_duration_min": int(estimated_duration_min),
        "status": "active",
        "created_at": datetime.utcnow(),
        "completed_at": None
    }
