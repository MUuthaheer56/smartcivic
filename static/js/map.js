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

let graphLayer;

async function showClusterGraph(issueId, targetMap = null) {
  const mapObj = targetMap || leafletMap || (typeof liveMap !== "undefined" ? liveMap : null);
  if (!mapObj || typeof L === "undefined") return;

  if (!graphLayer) {
    graphLayer = L.layerGroup().addTo(mapObj);
  } else {
    graphLayer.clearLayers();
  }

  try {
    const res = await fetch(`/api/issues/${issueId}/graph`, { credentials: "same-origin" });
    if (!res.ok) return;
    const g = await res.json();
    const byId = Object.fromEntries((g.nodes || []).map(n => [n.id, n]));
    
    (g.edges || []).forEach(e => {
      const a = byId[e.from], b = byId[e.to];
      if (!a || !b) return;
      L.polyline([[a.lat, a.lng], [b.lat, b.lng]], {
        color: "#888",
        weight: 1 + 4 * (e.weight || 0.5),
        dashArray: "6 6"
      }).bindTooltip(`${e.rule} (wt: ${e.weight})`).addTo(graphLayer);
    });
    
    (g.nodes || []).forEach(n => {
      const root = n.role === "root";
      L.circleMarker([n.lat, n.lng], {
        radius: root ? 11 : 7,
        color: root ? "#c62828" : "#ef6c00",
        fillOpacity: 0.85,
        className: root ? "pulse-root" : ""
      }).bindPopup(`<b>${escapeHtml(n.category || "Issue")}</b><br>Dept: ${escapeHtml(n.department || "Unassigned")}<br>Role: ${escapeHtml(n.role || "member")}`).addTo(graphLayer);
    });
  } catch (err) {
    console.error("Failed to load cluster graph:", err);
  }
}

function escapeHtml(str) {
  return String(str || "").replace(/[&<>'"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[c]);
}

if (typeof socket !== "undefined") {
  socket.on("cluster_updated", ({ root_id }) => {
    showClusterGraph(root_id);
  });
}
