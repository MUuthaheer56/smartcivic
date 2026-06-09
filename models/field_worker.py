from bson import ObjectId
from app import db

class FieldWorker:
    @staticmethod
    def get_by_id(worker_id):
        if isinstance(worker_id, str):
            try:
                worker_id = ObjectId(worker_id)
            except Exception:
                return None
        return db.field_workers.find_one({"_id": worker_id})

    @staticmethod
    def create_or_update(worker_id, name, email, assigned_community, lat=0.0, lng=0.0):
        if isinstance(worker_id, str):
            worker_id = ObjectId(worker_id)
        if isinstance(assigned_community, str) and assigned_community:
            assigned_community = ObjectId(assigned_community)
            
        doc = {
            "name": name,
            "email": email,
            "assigned_community": assigned_community,
            "current_location": {"lat": float(lat), "lng": float(lng)},
            "active_route": None
        }
        db.field_workers.update_one(
            {"_id": worker_id},
            {"$set": doc},
            upsert=True
        )

    @staticmethod
    def update_location(worker_id, lat, lng):
        if isinstance(worker_id, str):
            worker_id = ObjectId(worker_id)
        db.field_workers.update_one(
            {"_id": worker_id},
            {"$set": {"current_location": {"lat": float(lat), "lng": float(lng)}}}
        )

    @staticmethod
    def set_active_route(worker_id, route_id):
        if isinstance(worker_id, str):
            worker_id = ObjectId(worker_id)
        if isinstance(route_id, str) and route_id:
            route_id = ObjectId(route_id)
        db.field_workers.update_one(
            {"_id": worker_id},
            {"$set": {"active_route": route_id}}
        )

    @staticmethod
    def get_by_community(community_id):
        if isinstance(community_id, str):
            try:
                community_id = ObjectId(community_id)
            except Exception:
                return []
        return list(db.field_workers.find({"assigned_community": community_id}))
