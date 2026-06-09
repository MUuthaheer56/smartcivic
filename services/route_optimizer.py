import math
import heapq
from typing import List, Dict

def haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371.0
    lat1, lng1, lat2, lng2 = map(math.radians, [lat1, lng1, lat2, lng2])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng/2)**2
    return 2 * R * math.asin(math.sqrt(a))

def build_graph(locations: List[Dict]) -> Dict:
    graph = {}
    for i, a in enumerate(locations):
        graph[a['id']] = {}
        for j, b in enumerate(locations):
            if i != j:
                graph[a['id']][b['id']] = haversine(a['lat'], a['lng'], b['lat'], b['lng'])
    return graph

def dijkstra(graph: Dict, start: str) -> tuple:
    dist = {n: float('inf') for n in graph}
    dist[start] = 0.0
    paths = {n: [] for n in graph}
    paths[start] = [start]
    pq = [(0.0, start)]
    while pq:
        cd, cn = heapq.heappop(pq)
        if cd > dist[cn]:
            continue
        for nb, w in graph.get(cn, {}).items():
            d = cd + w
            if d < dist[nb]:
                dist[nb] = d
                paths[nb] = paths[cn] + [nb]
                heapq.heappush(pq, (d, nb))
    return dist, paths

def nearest_neighbor_route(start_id: str, locations: List[Dict], graph: Dict) -> List[str]:
    remaining = [l['id'] for l in locations if l['id'] != start_id]
    route = []
    current = start_id
    sev_map = {l['id']: l.get('severity', 3) for l in locations}
    while remaining:
        dists, _ = dijkstra(graph, current)
        # Sort by distance divided by severity to prioritize severe closer issues
        best = min(remaining, key=lambda c: dists.get(c, float('inf')) / max(1, sev_map.get(c, 1)))
        route.append(best)
        remaining.remove(best)
        current = best
    return route

def optimize_route(worker_lat: float, worker_lng: float, issues: List[Dict]) -> Dict:
    depot = {'id': 'depot', 'lat': worker_lat, 'lng': worker_lng, 'severity': 1}
    locs = [depot] + [{'id': str(i['_id']), 'lat': i['lat'], 'lng': i['lng'], 'severity': i.get('severity', 3)} for i in issues]
    graph = build_graph(locs)
    ordered = nearest_neighbor_route('depot', locs, graph)
    imap = {str(i['_id']): i for i in issues}
    
    # Prepend depot starting point as the first waypoint (sequence 0)
    waypoints = [{
        'issue_id': 'depot',
        'lat': worker_lat,
        'lng': worker_lng,
        'sequence': 0,
        'title': 'Starting Depot',
        'severity': 1,
        'category': 'depot',
        'address': 'Worker Start Location'
    }]
    
    total = 0.0
    plat, plng = worker_lat, worker_lng
    for seq, iid in enumerate(ordered, 1):
        iss = imap.get(iid)
        if iss:
            waypoints.append({
                'issue_id': iid,
                'lat': iss['lat'],
                'lng': iss['lng'],
                'sequence': seq,
                'title': iss.get('title', ''),
                'severity': iss.get('severity', 3),
                'category': iss.get('category', ''),
                'address': iss.get('address', '')
            })
            total += haversine(plat, plng, iss['lat'], iss['lng'])
            plat, plng = iss['lat'], iss['lng']
            
    return {
        'ordered_issue_ids': ordered,
        'waypoints': waypoints,
        'total_distance_km': round(total, 2),
        'estimated_duration_min': int((total / 30) * 60) # assuming average 30 km/h
    }
