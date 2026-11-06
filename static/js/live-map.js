let liveMap;
let issueLayer;
let userLocationMarker;
let userAccuracyCircle;
let refreshTimer;
let currentIssues = [];

const defaultMapCenter = [12.9716, 77.5946];
const refreshIntervalMs = 15000;

window.addEventListener("DOMContentLoaded", () => {
    liveMap = L.map("liveMap", { zoomControl: true }).setView(defaultMapCenter, 13);
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark' || document.documentElement.classList.contains('dark');
    const tileUrl = isDark 
        ? "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
        : "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png";

    const tileLayer = L.tileLayer(tileUrl, {
        maxZoom: 19,
        attribution: "&copy; OpenStreetMap contributors &copy; CARTO"
    }).addTo(liveMap);

    // Tile error detection (UI-REPAIR requirement 5)
    tileLayer.on('tileerror', (err) => {
        console.warn("Tile layer error detected:", err);
        const tileErrEl = document.getElementById("mapTileErrorNotice");
        if (tileErrEl) {
            tileErrEl.style.display = "block";
        }
    });

    issueLayer = L.layerGroup().addTo(liveMap);
    document.getElementById("locateMapButton")?.addEventListener("click", locateMapUser);
    document.getElementById("refreshMapButton")?.addEventListener("click", () => loadLiveIssues(true));

    // Listen for bounds change to reload visible issues (UI-REPAIR requirement 5)
    liveMap.on("moveend", () => {
        loadLiveIssues(false);
    });

    loadLiveIssues(false);
    refreshTimer = window.setInterval(() => loadLiveIssues(false), refreshIntervalMs);
});

window.addEventListener("beforeunload", () => {
    if (refreshTimer) window.clearInterval(refreshTimer);
});

async function loadLiveIssues(showFeedback) {
    const status = document.getElementById("mapStatus");
    if (showFeedback && status) status.textContent = "Refreshing active reports...";

    // Visible bounding box query (UI-REPAIR requirement 5)
    let url = "/api/public/map";
    if (liveMap && typeof liveMap.getBounds === "function") {
        try {
            const bounds = liveMap.getBounds();
            const minLat = bounds.getSouth();
            const minLng = bounds.getWest();
            const maxLat = bounds.getNorth();
            const maxLng = bounds.getEast();
            if (isFinite(minLat) && isFinite(minLng) && isFinite(maxLat) && isFinite(maxLng)) {
                url += `?min_lat=${minLat.toFixed(6)}&min_lng=${minLng.toFixed(6)}&max_lat=${maxLat.toFixed(6)}&max_lng=${maxLng.toFixed(6)}`;
            }
        } catch (e) {
            console.warn("Bounds calculation error:", e);
        }
    }

    try {
        const fetchFn = window.api || window.fetch;
        const res = await fetchFn(url, { headers: { Accept: "application/json" } });
        const payload = (typeof res.json === "function" && !(res instanceof Response)) ? res : (res.data ? res : await res.json());
        
        if (!payload || !payload.success) {
            throw new Error((payload && payload.error && payload.error.message) || "Map data unavailable");
        }

        currentIssues = payload.data || [];
        renderIssues(currentIssues);
        if (status) {
            status.textContent = `Updated ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}. Auto-refreshes every 15 seconds.`;
        }
    } catch (error) {
        console.error("Live map loading failed:", error);
        if (status) {
            status.innerHTML = `<span style="color: #ef4444;"><i class="fa-solid fa-triangle-exclamation"></i> Unable to load live reports.</span> <button id="retryLiveMapBtn" class="btn btn-secondary" style="padding: 2px 8px; font-size: 0.75rem; margin-left: 8px; cursor: pointer;">Retry</button>`;
            document.getElementById("retryLiveMapBtn")?.addEventListener("click", () => loadLiveIssues(true));
        }
        const list = document.getElementById("mapIssueList");
        if (list && (!currentIssues || currentIssues.length === 0)) {
            list.innerHTML = `
                <div class="error-retry-state" style="text-align: center; padding: 2.5rem; color: var(--text-muted, #94a3b8);">
                    <i class="fa-solid fa-triangle-exclamation" style="font-size: 2rem; color: #ef4444; margin-bottom: 0.75rem;"></i>
                    <p style="margin-bottom: 1rem; color: var(--text-main, #f8fafc);">Failed to load civic reports.</p>
                    <button id="retryListBtn" type="button" class="btn btn-primary" style="padding: 0.4rem 1rem; font-size: 0.85rem; cursor: pointer;">
                        <i class="fa-solid fa-rotate-right"></i> Retry
                    </button>
                </div>
            `;
            document.getElementById("retryListBtn")?.addEventListener("click", () => loadLiveIssues(true));
        }
    }
}

/**
 * Cluster points within pixel distance on map (UI-REPAIR requirement 5)
 */
function clusterIssues(issues, radiusPx = 50) {
    if (!liveMap) return issues.map(iss => ({ centerLat: (iss.location?.coordinates || [])[1], centerLng: (iss.location?.coordinates || [])[0], issues: [iss] }));
    
    const clusters = [];
    issues.forEach(iss => {
        const coords = iss.location?.coordinates || [];
        if (coords.length !== 2) return;
        const [lng, lat] = coords;
        const pt = liveMap.latLngToLayerPoint([lat, lng]);

        let added = false;
        for (const cluster of clusters) {
            const clusterPt = liveMap.latLngToLayerPoint([cluster.centerLat, cluster.centerLng]);
            const dist = pt.distanceTo(clusterPt);
            if (dist <= radiusPx) {
                cluster.issues.push(iss);
                // Recompute centroid
                const totalLat = cluster.issues.reduce((acc, cur) => acc + cur.location.coordinates[1], 0);
                const totalLng = cluster.issues.reduce((acc, cur) => acc + cur.location.coordinates[0], 0);
                cluster.centerLat = totalLat / cluster.issues.length;
                cluster.centerLng = totalLng / cluster.issues.length;
                added = true;
                break;
            }
        }
        if (!added) {
            clusters.push({
                centerLat: lat,
                centerLng: lng,
                issues: [iss]
            });
        }
    });
    return clusters;
}

function renderIssues(issues) {
    issueLayer.clearLayers();
    const list = document.getElementById("mapIssueList");
    const count = document.getElementById("mapIssueCount");
    if (count) count.textContent = `${issues.length} report${issues.length === 1 ? "" : "s"}`;
    if (!list) return;
    list.innerHTML = "";

    if (!issues.length) {
        list.innerHTML = '<div class="map-empty-state"><i class="fa-solid fa-check-circle" style="color: var(--jewel-emerald, #0f9d6b);"></i><span>No active reports in the visible map area.</span></div>';
        return;
    }

    // Client-side clustering
    const clusters = clusterIssues(issues, 45);

    clusters.forEach(cluster => {
        if (cluster.issues.length === 1) {
            const issue = cluster.issues[0];
            const coordinates = issue.location?.coordinates || [];
            if (coordinates.length !== 2) return;
            const [lng, lat] = coordinates;
            const severity = String(issue.severity || "medium").toLowerCase();
            const marker = L.circleMarker([lat, lng], {
                radius: severity === "critical" ? 10 : 8,
                color: "#c9a227",
                fillColor: severityColor(severity),
                fillOpacity: 0.85,
                weight: 1.5
            });
            marker.bindPopup(buildPopup(issue));
            marker.addTo(issueLayer);
        } else {
            // Group cluster badge
            const count = cluster.issues.length;
            const hasCritical = cluster.issues.some(i => String(i.severity).toLowerCase() === 'critical');
            const bgColor = hasCritical ? '#d1264a' : 'var(--primary, #3b82f6)';
            
            const clusterIcon = L.divIcon({
                className: 'civic-cluster-marker',
                html: `<div style="background: ${bgColor}; color: #ffffff; border-radius: 50%; width: 34px; height: 34px; display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 0.85rem; border: 2px solid #ffffff; box-shadow: 0 2px 8px rgba(0,0,0,0.4); cursor: pointer;">${count}</div>`,
                iconSize: [34, 34],
                iconAnchor: [17, 17]
            });
            const clusterMarker = L.marker([cluster.centerLat, cluster.centerLng], { icon: clusterIcon });
            clusterMarker.bindPopup(`
                <div class="map-popup">
                    <strong>Cluster: ${count} Civic Reports</strong>
                    <div style="font-size: 0.8rem; margin-top: 4px; color: var(--text-muted, #94a3b8);">Click to zoom into this cluster</div>
                </div>
            `);
            clusterMarker.on('click', () => {
                liveMap.setView([cluster.centerLat, cluster.centerLng], Math.min(liveMap.getZoom() + 2, 18));
            });
            clusterMarker.addTo(issueLayer);
        }
    });

    // Sidebar list
    issues.forEach(issue => {
        const coordinates = issue.location?.coordinates || [];
        if (coordinates.length !== 2) return;
        const [lng, lat] = coordinates;
        const severity = String(issue.severity || "medium").toLowerCase();

        const item = document.createElement("button");
        item.type = "button";
        item.className = "map-issue-item";
        item.innerHTML = `<span class="severity-dot severity-${escapeHtml(severity)}"></span><span><strong>${escapeHtml(issue.category || "Civic report")}</strong><small>${escapeHtml(issue.ward || "Location unavailable")} &bull; ${escapeHtml(issue.status || "active")}</small></span>`;
        item.addEventListener("click", () => {
            liveMap.setView([lat, lng], Math.max(liveMap.getZoom(), 16));
        });
        list.appendChild(item);
    });
}

function buildPopup(issue) {
    return `<div class="map-popup"><strong>${escapeHtml(issue.category || "Civic report")}</strong><span>${escapeHtml(issue.status || "active")} &bull; ${escapeHtml(issue.severity || "medium")}</span><small>${escapeHtml(issue.ward || "Ward unavailable")} &bull; ${issue.confirmation_count || 0} confirmations</small></div>`;
}

function locateMapUser() {
    const button = document.getElementById("locateMapButton");
    const note = document.getElementById("locationNote");
    if (!navigator.geolocation) {
        if (note) note.innerHTML = '<i class="fa-solid fa-triangle-exclamation" style="color: var(--jewel-ruby, #d1264a);"></i> Location is not supported by this browser.';
        return;
    }

    if (button) {
        button.disabled = true;
        button.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Locating';
    }
    navigator.geolocation.getCurrentPosition(
        ({ coords }) => {
            const position = [coords.latitude, coords.longitude];
            if (userLocationMarker) userLocationMarker.remove();
            if (userAccuracyCircle) userAccuracyCircle.remove();
            userLocationMarker = L.marker(position).addTo(liveMap).bindPopup("You are here").openPopup();
            userAccuracyCircle = L.circle(position, { 
                radius: coords.accuracy, 
                color: "#c9a227",
                fillColor: "#6d28d9",
                fillOpacity: 0.15, 
                weight: 1.5 
            }).addTo(liveMap);
            liveMap.setView(position, 16);
            if (note) note.innerHTML = '<i class="fa-solid fa-location-dot" style="color: var(--accent-gold, #c9a227);"></i> Your location is shown on this device only.';
            if (button) resetLocateButton(button);
        },
        (error) => {
            const message = error.code === error.PERMISSION_DENIED ? "Location permission was denied." : "Your location could not be detected.";
            if (note) note.innerHTML = `<i class="fa-solid fa-triangle-exclamation" style="color: var(--jewel-ruby, #d1264a);"></i> ${message}`;
            if (button) resetLocateButton(button);
        },
        { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 }
    );
}

function resetLocateButton(button) {
    button.disabled = false;
    button.innerHTML = '<i class="fa-solid fa-location-crosshairs"></i> Use my location';
}

function severityColor(severity) {
    return { 
        critical: "#d1264a",
        high: "#e0701a",
        medium: "#d99a1a",
        low: "#0f9d6b"
    }[severity] || "#6b6a8a";
}

function escapeHtml(value) {
    if (value === null || value === undefined) return '';
    return String(value).replace(/[&<>'"]/g, character => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]);
}
