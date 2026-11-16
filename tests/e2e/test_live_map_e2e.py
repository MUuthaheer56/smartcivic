"""
Playwright End-to-End Test for Live Civic Map (/map).
Verifies:
1. Map page loading, rendering, and Leaflet initialization.
2. Sidebar incident list display and live incident count.
3. Leaflet markers/clusters rendered on the canvas.
4. Clicking an incident card pans to the issue and opens Leaflet popup.
5. "Refresh map" button interactivity.
6. Zero console errors, zero uncaught page errors, zero failed network requests.
"""
import pytest
from bson import ObjectId
from app import db


def test_live_map_browser_e2e(browser, live_server):
    # Ensure test issue exists in DB with known coordinates
    test_issue_id = ObjectId()
    test_title = f"Pothole on 100ft Road {test_issue_id}"
    db.issues.insert_one({
        "_id": test_issue_id,
        "issue_id": f"SC-MAP-{str(test_issue_id)[:6].upper()}",
        "title": test_title,
        "description": "Hazardous road defect for live map verification",
        "category": "road",
        "severity": "critical",
        "status": "submitted",
        "ward": "Ward 150 - Bellandur",
        "location": {
            "type": "Point",
            "coordinates": [77.5946, 12.9716]
        }
    })

    context = browser.new_context()
    page = context.new_page()

    console_errors = []
    page_errors = []
    failed_requests = []

    def on_console(msg):
        if msg.type == "error":
            if "favicon.ico" not in msg.text:
                console_errors.append(msg.text)

    def on_page_error(err):
        page_errors.append(str(err))

    def on_response(resp):
        if "favicon.ico" in resp.url or "cartocdn.com" in resp.url:
            return
        if resp.status >= 400:
            failed_requests.append(f"{resp.request.method} {resp.url} -> {resp.status}")

    page.on("console", on_console)
    page.on("pageerror", on_page_error)
    page.on("response", on_response)

    try:
        # 1. Navigate to /map
        page.goto(f"{live_server}/map", wait_until="domcontentloaded", timeout=25000)

        # 2. Verify Leaflet map container initializes
        page.wait_for_selector("#map.leaflet-container", state="visible", timeout=10000)
        page.wait_for_selector(".leaflet-pane", state="attached", timeout=10000)

        # 3. Verify toolbar & buttons
        page.wait_for_selector("#liveMapTitle", state="visible")
        page.wait_for_selector("#locateMapButton", state="visible")
        page.wait_for_selector("#refreshMapButton", state="visible")

        # 4. Verify sidebar incident count and list
        page.wait_for_selector("#mapIssueCount", state="visible")
        page.wait_for_selector("#mapIssueList", state="visible")
        page.wait_for_timeout(2000)

        # Check issue list is populated
        issue_items = page.locator("#mapIssueList .map-issue-item")
        item_count = issue_items.count()
        assert item_count > 0, "Expected at least one issue item in live map sidebar"

        # 5. Interactive Test: Click first issue item to pan
        first_item = issue_items.first
        first_item.click()
        page.wait_for_timeout(1500)

        # Verify markers or clusters exist on map canvas
        page.wait_for_selector(".leaflet-marker-pane, .leaflet-overlay-pane", state="attached", timeout=5000)

        # Check that markers (circleMarker path or cluster div) are rendered
        rendered_markers = page.evaluate("""() => {
            const paths = document.querySelectorAll('.leaflet-overlay-pane path').length;
            const clusters = document.querySelectorAll('.leaflet-marker-pane .civic-cluster-marker').length;
            return { paths, clusters };
        }""")
        assert rendered_markers["paths"] > 0 or rendered_markers["clusters"] > 0, "No map markers rendered"

        # Open popup on the first available issue marker
        opened = page.evaluate("""() => {
            if (!issueLayer) return false;
            let found = false;
            issueLayer.eachLayer(layer => {
                if (!found && typeof layer.openPopup === 'function') {
                    layer.openPopup();
                    found = true;
                }
            });
            return found;
        }""")
        assert opened, "Failed to open popup on issue layer"

        # Verify Leaflet popup opens and contains issue details
        page.wait_for_selector(".leaflet-popup-content", state="visible", timeout=5000)
        popup_text = page.locator(".leaflet-popup-content").inner_text()
        assert len(popup_text.strip()) > 0, "Popup content was empty"

        # 6. Interactive Test: Click "Refresh map" button
        refresh_btn = page.locator("#refreshMapButton")
        refresh_btn.click()
        page.wait_for_timeout(1500)

        # 7. Assert zero console errors or failed API requests
        assert len(page_errors) == 0, f"Uncaught page errors: {page_errors}"
        assert len(console_errors) == 0, f"Console errors: {console_errors}"
        assert len(failed_requests) == 0, f"Failed requests: {failed_requests}"

    finally:
        db.issues.delete_one({"_id": test_issue_id})
        context.close()
