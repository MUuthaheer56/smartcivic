# db.communities schema representation:
# {
#   _id: ObjectId,
#   name: str,
#   city: str,
#   state: str,
#   lat: float,
#   lng: float,
#   boundary_radius_km: float,
#   community_score: int(0-100, starts 100),
#   total_issues: int(0),
#   resolved_issues: int(0),
#   open_issues: int(0),
#   created_at: datetime,
#   score_history: [{score:int, change:int, reason:str, timestamp:datetime}] (last 30)
# }

def create_community_doc(name, city, state, lat, lng, boundary_radius_km):
    from datetime import datetime
    return {
        "name": name,
        "city": city,
        "state": state,
        "lat": float(lat),
        "lng": float(lng),
        "boundary_radius_km": float(boundary_radius_km),
        "community_score": 100,
        "total_issues": 0,
        "resolved_issues": 0,
        "open_issues": 0,
        "created_at": datetime.utcnow(),
        "score_history": []
    }
