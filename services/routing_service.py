import json
import urllib.request
import urllib.error
import math
from typing import Dict, List, Any, Tuple

OSRM_BACKEND_URL = "https://router.project-osrm.org"

class RoutingService:
    @staticmethod
    def calculate_haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Fallback great-circle distance in meters."""
        R = 6371000  # Earth radius in meters
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)

        a = math.sin(delta_phi / 2.0) ** 2 + \
            math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

    @classmethod
    def get_road_route(cls, origin: Tuple[float, float], destination: Tuple[float, float]) -> Dict[str, Any]:
        """
        Queries OSRM to generate real road routes rather than straight Euclidean lines.
        Returns GeoJSON geometry, distance (meters), duration (seconds), and turn-by-turn steps.
        """
        lat1, lon1 = origin
        lat2, lon2 = destination

        # Input boundary validation
        if not (-90 <= lat1 <= 90 and -180 <= lon1 <= 180 and -90 <= lat2 <= 90 and -180 <= lon2 <= 180):
            raise ValueError("Coordinates are outside valid geographic bounds.")

        # OSRM coordinate order: {longitude},{latitude}
        url = f"{OSRM_BACKEND_URL}/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=full&geometries=geojson&steps=true"

        req = urllib.request.Request(
            url,
            headers={"User-Agent": "SmartCivic-RoadRouter/2.0 (CivicTech Infrastructure)"}
        )

        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode('utf-8'))
                    if data.get("code") == "Ok" and len(data.get("routes", [])) > 0:
                        primary_route = data["routes"][0]
                        return {
                            "status": "SUCCESS",
                            "is_real_road": True,
                            "distance_meters": round(primary_route["distance"], 1),
                            "duration_seconds": round(primary_route["duration"], 1),
                            "eta_minutes": round(primary_route["duration"] / 60.0, 1),
                            "geometry": primary_route["geometry"],  # GeoJSON LineString
                            "legs": primary_route.get("legs", [])
                        }
        except Exception as e:
            # Resilient fallback: Compute approximate straight-line route if external network is unavailable
            pass

        # Fallback straight-line calculation with 1.3x urban circuity factor
        direct_dist = cls.calculate_haversine_distance(lat1, lon1, lat2, lon2)
        estimated_road_dist = direct_dist * 1.3
        estimated_seconds = (estimated_road_dist / 8.33)  # Approx 30 km/h urban speed

        return {
            "status": "FALLBACK_OFFLINE",
            "is_real_road": False,
            "distance_meters": round(estimated_road_dist, 1),
            "duration_seconds": round(estimated_seconds, 1),
            "eta_minutes": round(estimated_seconds / 60.0, 1),
            "geometry": {
                "type": "LineString",
                "coordinates": [[lon1, lat1], [lon2, lat2]]
            },
            "legs": []
        }
