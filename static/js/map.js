/**
 * SmartCivic — Common Map JS (Royal Civic Cartography)
 * Handles common Map initialization and marker plotting.
 */
let leafletMap;

function initCommonMap(elementId, center = [12.9716, 77.5946], zoom = 13) {
  leafletMap = L.map(elementId).setView(center, zoom);
  const isDark = document.documentElement.getAttribute('data-theme') === 'dark' || document.documentElement.classList.contains('dark');
  const tileUrl = isDark
    ? 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
    : 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png';

  L.tileLayer(tileUrl, {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap &copy; CARTO'
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
        color: "#6d28d9", // Royal Purple causal edge
        weight: 1.5 + 4 * (e.weight || 0.5),
        dashArray: "6 6",
        opacity: 0.85
      }).bindTooltip(`${e.rule} (wt: ${e.weight})`).addTo(graphLayer);
    });

    (g.nodes || []).forEach(n => {
      const root = n.role === "root";
      L.circleMarker([n.lat, n.lng], {
        radius: root ? 12 : 7,
        color: root ? "#c9a227" : "#6d28d9", // Imperial Gold ring for root, Royal Purple for nodes
        weight: root ? 2.5 : 1.5,
        fillColor: root ? "#d1264a" : "#d99a1a", // Jewel Ruby for root, Amber Gold for members
        fillOpacity: 0.9,
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
