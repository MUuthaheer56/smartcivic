import json
import pathlib
from shapely.geometry import Point, shape
import pyproj

BUFFER_METRES = 30  # KTCP Act protected buffer

# load boundaries once at module level
_geojson_path = pathlib.Path(__file__).parent / "data" / "bengaluru_lakes.geojson"
_lake_features = []
if _geojson_path.exists():
    try:
        data = json.loads(_geojson_path.read_text())
        _lake_features = data.get("features", [])
    except Exception as e:
        print(f"[GeoJSON] Error loading lakes: {e}")

# projections for accurate metric buffering
_wgs84 = pyproj.CRS("EPSG:4326")
_utm43 = pyproj.CRS("EPSG:32643")  # UTM zone 43N (covers Bengaluru)
_project_to_utm = pyproj.Transformer.from_crs(_wgs84, _utm43, always_xy=True).transform
_project_to_wgs = pyproj.Transformer.from_crs(_utm43, _wgs84, always_xy=True).transform

def check_lake_buffer(lat: float, lng: float) -> dict:
    point_wgs = Point(lng, lat)

    for feature in _lake_features:
        lake_geom = shape(feature["geometry"])
        lake_name = feature.get("properties", {}).get("name", "Unknown water body")

        # project to UTM for accurate metre-based buffer
        from shapely.ops import transform as shp_transform
        lake_utm = shp_transform(_project_to_utm, lake_geom)
        buffered_utm = lake_utm.buffer(BUFFER_METRES)

        # project buffer back to WGS84 for point-in-polygon check
        buffered_wgs = shp_transform(_project_to_wgs, buffered_utm)
        inside_lake = lake_geom.contains(point_wgs)
        inside_buffer = buffered_wgs.contains(point_wgs)

        if inside_lake or inside_buffer:
            dist = lake_geom.exterior.distance(point_wgs) * 111000  # approx metres
            return {
                "violation": True,
                "water_body": lake_name,
                "distance_from_boundary_m": round(dist, 1),
                "inside_lake": inside_lake,
                "inside_buffer_zone": inside_buffer,
                "buffer_m": BUFFER_METRES,
                "legal_reference": "KTCP Act — 30m buffer zone",
                "escalation": "REVENUE_DEPARTMENT",
                "priority_override": "CRITICAL"
            }

    return {"violation": False}
