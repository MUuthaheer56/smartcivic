/**
 * SmartCivic+ — Common Map JS
 * Handles common Map initialization and marker plotting.
 */
let leafletMap;

function initCommonMap(elementId, center = [12.9716, 77.5946], zoom = 13) {
    leafletMap = L.map(elementId).setView(center, zoom);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '© OpenStreetMap contributors'
    }).addTo(leafletMap);
    return leafletMap;
}
