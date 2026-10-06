"""
SmartCivic+ — Predictive Hotspot Analysis Service
Performs geospatial clustering and recurrence risk calculations based on historical closed complaints.
Only activates if closed complaints count >= 100.
"""
from datetime import datetime, timedelta
from bson import ObjectId
from app import db

def compute_hotspots() -> list:
    """
    1. Check if closed complaint count >= 100. If not, return [].
    2. Group closed complaints by location grid (0.01 degree cells ~ 1km) and category.
    3. For each cell with >= 3 complaints:
       - Calculate recurrence_rate = complaint_count / months_active
       - Assign hotspot_risk: high / medium / low based on recurrence_rate
    4. Return list of hotspot dicts.
    5. Cache result in MongoDB (hotspots collection). Recalculate weekly.
    """
    print("[Prediction Service] Computing predictive hotspots...")
    
    closed_count = db.issues.count_documents({"status": "closed"})
    if closed_count < 100:
        print(f"[Prediction Service] Insufficient closed complaints data ({closed_count}/100 needed). Skipping computation.")
        # Ensure we return an empty list but don't crash
        db.hotspots.delete_many({})
        return []
        
    closed_issues = list(db.issues.find({"status": "closed"}))
    
    # Grid cell resolution: 0.01 degree is approx 1.1km
    # Group issues into grid keys: (rounded_lat, rounded_lng, category)
    grid = {}
    for issue in closed_issues:
        coords = issue.get("location", {}).get("coordinates", [0.0, 0.0])
        lng, lat = coords[0], coords[1]
        category = issue.get("category", "other")
        
        # Round to 2 decimal places to create a 1km grid
        lat_grid = round(lat, 2)
        lng_grid = round(lng, 2)
        grid_key = (lat_grid, lng_grid, category)
        
        if grid_key not in grid:
            grid[grid_key] = []
        grid[grid_key].append(issue)
        
    hotspots = []
    now = datetime.utcnow()
    
    for (lat_grid, lng_grid, category), issues in grid.items():
        issue_count = len(issues)
        if issue_count >= 3:
            # Sort by created_at to find months active
            issues.sort(key=lambda x: x.get("created_at") or now)
            earliest = issues[0].get("created_at") or now
            latest = issues[-1].get("created_at") or now
            
            delta_days = max(1, (latest - earliest).days)
            months_active = max(1.0, delta_days / 30.0)
            
            recurrence_rate = round(issue_count / months_active, 2)
            
            # Risk categorization
            if recurrence_rate >= 1.5:
                risk = "high"
            elif recurrence_rate >= 0.7:
                risk = "medium"
            else:
                risk = "low"
                
            hotspots.append({
                "lat": lat_grid,
                "lng": lng_grid,
                "category": category,
                "recurrence_rate": recurrence_rate,
                "hotspot_risk": risk,
                "complaint_count": issue_count
            })
            
    # Cache result in hotspots collection
    db.hotspots.delete_many({})
    if hotspots:
        db.hotspots.insert_many(hotspots)
        
    return hotspots
