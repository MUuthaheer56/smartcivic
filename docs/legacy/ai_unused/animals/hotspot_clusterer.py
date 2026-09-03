from datetime import datetime, timedelta

CLUSTER_RADIUS_DEG = 200 / 111000  # 200m in degrees
HOTSPOT_MIN_REPORTS = 5
HOTSPOT_WINDOW_DAYS = 7

def compute_animal_hotspots(db) -> list:
    cutoff = datetime.utcnow() - timedelta(days=HOTSPOT_WINDOW_DAYS)
    reports = list(db.issues.find({
        "category": {"$in": ["stray animal", "animal"]},
        "created_at": {"$gte": cutoff}
    }))

    # simple grid clustering
    clusters = []
    used = set()
    for i, r in enumerate(reports):
        if i in used:
            continue
        lat0 = r["lat"]
        lng0 = r["lng"]
        group = [r]
        for j, r2 in enumerate(reports):
            if j == i or j in used:
                continue
            if (abs(r2["lat"] - lat0) < CLUSTER_RADIUS_DEG and
                abs(r2["lng"] - lng0) < CLUSTER_RADIUS_DEG):
                group.append(r2)
                used.add(j)
        if len(group) >= HOTSPOT_MIN_REPORTS:
            avg_lat = sum(x["lat"] for x in group) / len(group)
            avg_lng = sum(x["lng"] for x in group) / len(group)
            animal_types = list({x.get("animal_type", "unknown") for x in group})
            clusters.append({
                "lat": avg_lat,
                "lng": avg_lng,
                "report_count": len(group),
                "animal_types": animal_types,
                "hotspot_score": len(group) * 10,
                "created_at": datetime.utcnow()
            })
        used.add(i)

    # save hotspots
    db.animal_hotspots.delete_many({})
    if clusters:
        db.animal_hotspots.insert_many(clusters)
    return sorted(clusters, key=lambda x: -x["hotspot_score"])
