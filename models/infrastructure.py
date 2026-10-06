"""
SmartCivic+ — Infrastructure Segment Model Schema
"""
from datetime import datetime

def create_infrastructure_doc(
    segment_id: str,
    segment_type: str, # "road", "drainage", "streetlight", "water", "garbage_point"
    name: str,
    coordinates: list, # List of [lng, lat] for Point, or list of list of [lng, lat] for LineString
    ward: str
) -> dict:
    now = datetime.utcnow()
    
    # Coordinates format for MongoDB 2dsphere indexing
    geo_type = "LineString" if any(isinstance(i, list) for i in coordinates) else "Point"
    
    return {
        "segment_id": segment_id,
        "segment_type": segment_type,
        "name": name,
        "location": {
            "type": geo_type,
            "coordinates": coordinates
        },
        "ward": ward,
        "health_score": 100,
        "complaint_count": 0,
        "repair_count": 0,
        "last_complaint_at": None,
        "last_repair_at": None,
        "created_at": now,
        "updated_at": now,
        "seeded": True
    }
