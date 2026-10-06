let liveMap;
let issueLayer;
let userLocationMarker;
let userAccuracyCircle;
let refreshTimer;

const defaultMapCenter = [12.9716, 77.5946];
const refreshIntervalMs = 15000;

window.addEventListener("DOMContentLoaded", () => {
    liveMap = L.map("liveMap", { zoomControl: true }).setView(defaultMapCenter, 13);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        attribution: "&copy; OpenStreetMap contributors"
    }).addTo(liveMap);

    issueLayer = L.layerGroup().addTo(liveMap);
    document.getElementById("locateMapButton").addEventListener("click", locateMapUser);
    document.getElementById("refreshMapButton").addEventListener("click", () => loadLiveIssues(true));

    loadLiveIssues(false);
    refreshTimer = window.setInterval(() => loadLiveIssues(false), refreshIntervalMs);
});

window.addEventListener("beforeunload", () => {
    if (refreshTimer) window.clearInterval(refreshTimer);
});

async function loadLiveIssues(showFeedback) {
    const status = document.getElementById("mapStatus");
    if (showFeedback) status.textContent = "Refreshing active reports...";

    try {
        const response = await fetch("/api/public/map", { headers: { Accept: "application/json" } });
        const payload = await response.json();
        if (!response.ok || !payload.success) throw new Error(payload.error?.message || "Map data unavailable");

        renderIssues(payload.data || []);
        status.textContent = `Updated ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}. Auto-refreshes every 15 seconds.`;
    } catch (error) {
        status.textContent = "Unable to load live reports. Check your connection and try again.";
        console.error("Live map loading failed:", error);
    }
}

function renderIssues(issues) {
    issueLayer.clearLayers();
    const list = document.getElementById("mapIssueList");
    const count = document.getElementById("mapIssueCount");
    count.textContent = `${issues.length} report${issues.length === 1 ? "" : "s"}`;
    list.innerHTML = "";

    if (!issues.length) {
        list.innerHTML = '<div class="map-empty-state"><i class="fa-solid fa-check-circle"></i><span>No active reports in the public feed.</span></div>';
        return;
    }

    issues.forEach((issue, index) => {
        const coordinates = issue.location?.coordinates || [];
        if (coordinates.length !== 2) return;
        const [lng, lat] = coordinates;
        const severity = String(issue.severity || "medium").toLowerCase();
        const marker = L.circleMarker([lat, lng], {
            radius: severity === "critical" ? 10 : 8,
            color: severityColor(severity),
            fillColor: severityColor(severity),
            fillOpacity: 0.78,
            weight: 2
        });
        marker.bindPopup(buildPopup(issue));
        marker.addTo(issueLayer);

        const item = document.createElement("button");
        item.type = "button";
        item.className = "map-issue-item";
        item.innerHTML = `<span class="severity-dot severity-${escapeHtml(severity)}"></span><span><strong>${escapeHtml(issue.category || "Civic report")}</strong><small>${escapeHtml(issue.ward || "Location unavailable")} · ${escapeHtml(issue.status || "active")}</small></span>`;
        item.addEventListener("click", () => {
            liveMap.setView([lat, lng], Math.max(liveMap.getZoom(), 15));
            marker.openPopup();
        });
        list.appendChild(item);
    });
}

function buildPopup(issue) {
    return `<div class="map-popup"><strong>${escapeHtml(issue.category || "Civic report")}</strong><span>${escapeHtml(issue.status || "active")} · ${escapeHtml(issue.severity || "medium")}</span><small>${escapeHtml(issue.ward || "Ward unavailable")} · ${issue.confirmation_count || 0} confirmations</small></div>`;
}

function locateMapUser() {
    const button = document.getElementById("locateMapButton");
    const note = document.getElementById("locationNote");
    if (!navigator.geolocation) {
        note.innerHTML = '<i class="fa-solid fa-triangle-exclamation"></i> Location is not supported by this browser.';
        return;
    }

    button.disabled = true;
    button.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Finding you';
    navigator.geolocation.getCurrentPosition(
        ({ coords }) => {
            const position = [coords.latitude, coords.longitude];
            if (userLocationMarker) userLocationMarker.remove();
            if (userAccuracyCircle) userAccuracyCircle.remove();
            userLocationMarker = L.marker(position).addTo(liveMap).bindPopup("You are here").openPopup();
            userAccuracyCircle = L.circle(position, { radius: coords.accuracy, color: "#0ea5e9", fillColor: "#38bdf8", fillOpacity: 0.16, weight: 1 }).addTo(liveMap);
            liveMap.setView(position, 16);
            note.innerHTML = '<i class="fa-solid fa-location-dot"></i> Your location is shown on this device only.';
            resetLocateButton(button);
        },
        (error) => {
            const message = error.code === error.PERMISSION_DENIED ? "Location permission was denied." : "Your location could not be detected.";
            note.innerHTML = `<i class="fa-solid fa-triangle-exclamation"></i> ${message}`;
            resetLocateButton(button);
        },
        { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 }
    );
}

function resetLocateButton(button) {
    button.disabled = false;
    button.innerHTML = '<i class="fa-solid fa-location-crosshairs"></i> Use my location';
}

function severityColor(severity) {
    return { critical: "#dc2626", high: "#ea580c", medium: "#0284c7", low: "#059669" }[severity] || "#64748b";
}

function escapeHtml(value) {
    return String(value).replace(/[&<>'"]/g, character => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]);
}
