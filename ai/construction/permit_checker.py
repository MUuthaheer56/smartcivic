def check_construction_permit(lat: float, lng: float, db) -> dict:
    """
    Check permit database in db.construction_permits collection.
    """
    radius_deg = 30 / 111000  # 30m radius

    permit = db.construction_permits.find_one({
        "lat": {"$gte": lat - radius_deg, "$lte": lat + radius_deg},
        "lng": {"$gte": lng - radius_deg, "$lte": lng + radius_deg},
        "status": "ACTIVE"
    })

    if permit:
        return {
            "permit_found": True,
            "permit_id": str(permit.get("permit_id")),
            "contractor": permit.get("contractor_name"),
            "valid_until": str(permit.get("valid_until")),
            "escalation_type": "SAFETY_VIOLATION_BY_LICENSED_CONTRACTOR"
        }
    else:
        return {
            "permit_found": False,
            "escalation_type": "POSSIBLE_ILLEGAL_CONSTRUCTION"
        }
