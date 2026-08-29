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
        return db.users.find_one({"_id": worker_id, "role": "field_worker"})

    @staticmethod
    def create_or_update(worker_id, name, email, community_id, lat=0.0, lng=0.0):
        if isinstance(worker_id, str):
            worker_id = ObjectId(worker_id)
        if isinstance(community_id, str) and community_id:
            community_id = ObjectId(community_id)
            
        doc = {
            "name": name,
            "email": email,
            "role": "field_worker",
            "community_id": community_id,
            "last_lat": float(lat),
            "last_lng": float(lng)
        }
        db.users.update_one(
            {"_id": worker_id},
            {"$set": doc},
            upsert=True
        )

    @staticmethod
    def update_location(worker_id, lat, lng):
        if isinstance(worker_id, str):
            worker_id = ObjectId(worker_id)
        db.users.update_one(
            {"_id": worker_id},
            {"$set": {"last_lat": float(lat), "last_lng": float(lng)}}
        )

    @staticmethod
    def set_active_route(worker_id, route_id):
        # db.users doesn't store active_route directly (it is fetched from db.routes),
        # but we preserve this signature as a no-op for backward compatibility.
        pass

    @staticmethod
    def get_by_community(community_id):
        if isinstance(community_id, str):
            try:
                community_id = ObjectId(community_id)
            except Exception:
                return []
        return list(db.users.find({"community_id": community_id, "role": "field_worker"}))
