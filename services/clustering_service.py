from datetime import datetime, timedelta
from bson import ObjectId
from collections import defaultdict

GRID = 0.005

def grid_key(lat: float, lng: float):
    return (round(lat / GRID) * GRID, round(lng / GRID) * GRID)

def cluster_issues_by_proximity(issues, radius_km=0.5):
    grid = defaultdict(list)
    for i in issues:
        key = grid_key(i['lat'], i['lng'])
        grid[key].append(i)
        
    clusters = []
    for key, cell in grid.items():
        priority = max(i.get('severity', 1) for i in cell) * len(cell)
        top_cat = max(set(i['category'] for i in cell), key=lambda c: sum(1 for i in cell if i['category'] == c))
        
        # Serialize the issues inside the cell for safety
        from utils import serialize
        serialized_cell = serialize(cell)
        
        clusters.append({
            'center_lat': round(key[0], 5),
            'center_lng': round(key[1], 5),
            'issues': serialized_cell,
            'count': len(cell),
            'priority': priority,
            'top_category': top_cat
        })
    return sorted(clusters, key=lambda c: c['priority'], reverse=True)

def get_community_hotspots(community_id, days=30):
    from app import db
    cutoff = datetime.utcnow() - timedelta(days=days)
    issues = list(db.issues.find(
        {
            'community_id': ObjectId(community_id),
            'status': {'$ne': 'rejected'},
            'created_at': {'$gte': cutoff}
        },
        {'lat': 1, 'lng': 1, 'category': 1, 'severity': 1, 'title': 1, 'description': 1, 'status': 1}
    ))
    return cluster_issues_by_proximity(issues)[:5]

def generate_municipal_recommendations(community_id, days=30):
    hotspots = get_community_hotspots(community_id, days=days)
    recommendations = []
    
    for idx, h in enumerate(hotspots):
        if h['count'] < 2:
            continue
            
        lat = h['center_lat']
        lng = h['center_lng']
        cat = h['top_category']
        count = h['count']
        
        if cat == 'pothole':
            title = "Schedule TC Palya Road Resurfacing"
            desc = f"Pothole Cluster Alert: {count} road damage reports detected near center [{lat}, {lng}]. Recommendation: Authorize a full road resurfacing work order rather than isolated spot patches to prevent re-occurrence."
            action = "Create Resurfacing Task"
        elif cat == 'garbage':
            title = "Deploy Varanasi Waste Dumpster"
            desc = f"Waste Accumulation Alert: {count} garbage overflow reports detected near center [{lat}, {lng}]. Recommendation: Install a high-capacity public dump container and increase trash collection sweep frequency to twice daily."
            action = "Place Waste Bin"
        elif cat == 'streetlight':
            title = "Electrical Grid Diagnostic & LED Upgrade"
            desc = f"Dark Lane Alert: {count} streetlight outages reported near center [{lat}, {lng}]. Recommendation: Conduct a comprehensive electrical wiring diagnostic in this lane and upgrade to LED fixtures."
            action = "Order Grid Check"
        elif cat == 'sewage':
            title = "Desilting & Drainage Pipe Clearing"
            desc = f"Sewage Outbreak Alert: {count} drainage overflow reports near center [{lat}, {lng}]. Recommendation: Dispatch a main sewer desilting team and inspect the underground pipeline diameter for capacity issues."
            action = "Dispatch Desilting Team"
        elif cat == 'water':
            title = "Water Utility Pipeline Leak Check"
            desc = f"Water Infrastructure Alert: {count} water leak/shortage reports near center [{lat}, {lng}]. Recommendation: Send a water inspector to verify main valves and replace corroded pipes."
            action = "Inspect Main Valves"
        else:
            title = f"Civic Inspection for {cat.capitalize()} Hotspot"
            desc = f"Civic Hotspot Alert: {count} reports of '{cat}' near center [{lat}, {lng}]. Recommendation: Deploy a local ward inspector to assess and resolve."
            action = "Deploy Civic Inspector"
            
        recommendations.append({
            'id': f"rec-{idx+1}",
            'title': title,
            'description': desc,
            'category': cat,
            'count': count,
            'lat': lat,
            'lng': lng,
            'action_label': action
        })
        
    return recommendations

