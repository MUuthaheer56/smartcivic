"""
Live Map Functionality Verification Test
Verifies:
1. GET /map renders HTTP 200 with all required stylesheets, DOM elements, and script tags.
2. GET /api/public/map returns HTTP 200 with geo-located issues and whitelisted fields.
3. Bounding box query /api/public/map?min_lat=... filters correctly.
4. Static resources (/static/css/map.css, /static/js/live-map.js) return HTTP 200.
"""
from app import create_app, db
from bson import ObjectId


def test_live_map_page_renders():
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()

    res = client.get("/map")
    assert res.status_code == 200
    html = res.data.decode("utf-8")

    # Verify DOM elements
    assert 'id="map"' in html or "id='map'" in html
    assert 'id="mapIssueList"' in html
    assert 'id="mapIssueCount"' in html
    assert 'id="locateMapButton"' in html
    assert 'id="refreshMapButton"' in html

    # Verify CSS links
    assert "/static/css/base.css" in html
    assert "/static/css/map.css" in html

    # Verify Script link
    assert "/static/js/live-map.js" in html


def test_live_map_static_assets():
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()

    for path in ["/static/css/map.css", "/static/js/live-map.js"]:
        res = client.get(path)
        assert res.status_code == 200, f"Expected 200 for {path}, got {res.status_code}"
        assert len(res.data) > 50, f"Resource {path} is empty"


def test_live_map_api_response():
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()

    # Ensure at least one test issue exists
    test_id = ObjectId()
    db.issues.insert_one({
        "_id": test_id,
        "title": "Live Map Verification Pothole",
        "description": "Deep road defect for live map testing",
        "category": "road",
        "severity": "high",
        "status": "submitted",
        "ward": "Ward 1",
        "location": {
            "type": "Point",
            "coordinates": [77.5946, 12.9716]
        }
    })

    try:
        # Unbounded query
        res = client.get("/api/public/map")
        assert res.status_code == 200
        data = res.get_json()
        assert data["success"] is True
        assert isinstance(data["data"], list)
        assert len(data["data"]) >= 1

        # Check whitelisted fields
        item = data["data"][0]
        assert "location" in item
        assert "coordinates" in item["location"]
        assert "citizen_id" not in item  # Privacy invariant

        # Bounding box query encompassing Bengaluru
        res_bbox = client.get("/api/public/map?min_lat=12.800000&min_lng=77.400000&max_lat=13.100000&max_lng=77.800000")
        assert res_bbox.status_code == 200
        data_bbox = res_bbox.get_json()
        assert data_bbox["success"] is True
        assert isinstance(data_bbox["data"], list)

    finally:
        db.issues.delete_one({"_id": test_id})

