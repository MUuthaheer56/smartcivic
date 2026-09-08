/**
 * SmartCivic+ — Citizen Dashboard JS
 * Updated: GPS location detection + map + complaint submission
 */
let map;
let marker;
let allCitizenIssues = [];
let citizenFilter;
let publicMarkers = [];

document.addEventListener("DOMContentLoaded", () => {
    initMap();
    citizenFilter = new SmartCivicFilter({
        containerId: 'filterBar',
        onFilterChange: () => renderCitizenIssues()
    });
    loadMyIssues();

    const form = document.getElementById("reportForm");
    if (form) {
        form.addEventListener("submit", submitIssue);
    }
});

function initMap() {
    // Default: Bangalore
    const defaultLat = 12.9716;
    const defaultLng = 77.5946;

    const mapContainer = document.getElementById('map');
    if (!mapContainer) {
        return;
    }

    map = L.map('map').setView([defaultLat, defaultLng], 13);

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '© OpenStreetMap contributors'
    }).addTo(map);

    marker = L.marker([defaultLat, defaultLng], { draggable: true }).addTo(map);
    updateCoords(defaultLat, defaultLng);

    setTimeout(() => {
        if (map) {
            map.invalidateSize();
        }
    }, 250);

    window.addEventListener('resize', () => {
        if (map) {
            map.invalidateSize();
        }
    });

    // Drag marker → update location
    marker.on('dragend', function (e) {
        const pos = marker.getLatLng();
        updateCoords(pos.lat, pos.lng);
        reverseGeocode(pos.lat, pos.lng);
    });

    // Click map → move marker
    map.on('click', function (e) {
        marker.setLatLng(e.latlng);
        updateCoords(e.latlng.lat, e.latlng.lng);
        reverseGeocode(e.latlng.lat, e.latlng.lng);
    });

    // Load other public issues on map
    loadPublicIssues();

    // Try to detect user location automatically
    tryDetectLocation();
}

/** Update hidden lat/lng fields */
function updateCoords(lat, lng) {
    const latEl = document.getElementById("lat");
    const lngEl = document.getElementById("lng");
    if (latEl) latEl.value = lat;
    if (lngEl) lngEl.value = lng;
}

/** Reverse geocode → fill address + ward */
async function reverseGeocode(lat, lng) {
    try {
        const res = await fetch(
            `https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lng}`,
            { headers: { 'Accept-Language': 'en' } }
        );
        const data = await res.json();
        if (data && data.display_name) {
            const addressEl = document.getElementById("address");
            if (addressEl) addressEl.value = data.display_name;

            const address = data.address || {};
            const ward = address.suburb || address.neighbourhood ||
                         address.quarter || address.city_district || "Ward 1";
            const wardEl = document.getElementById("ward");
            if (wardEl) wardEl.value = ward;
        }
    } catch (err) {
        console.error("Reverse geocoding failed:", err);
    }
}

/** Detect current GPS location */
function tryDetectLocation() {
    if (!navigator.geolocation) {
        console.warn("Geolocation is not supported by this browser.");
        return;
    }

    navigator.geolocation.getCurrentPosition(
        (pos) => {
            const lat = pos.coords.latitude;
            const lng = pos.coords.longitude;

            map.setView([lat, lng], 16);
            marker.setLatLng([lat, lng]);
            updateCoords(lat, lng);
            reverseGeocode(lat, lng);

            if (typeof showToast === "function") {
                showToast("Location detected successfully", "success");
            }
        },
        (err) => {
            console.warn("GPS error:", err.message);
            // Keep default Bangalore pin — user can still drag/click
        },
        {
            enableHighAccuracy: true,
            timeout: 12000,
            maximumAge: 60000
        }
    );
}

/** Button handler — call this from "Use my location" button */
function locateMe() {
    if (typeof showToast === "function") {
        showToast("Detecting your location...", "info");
    }
    tryDetectLocation();
}

/** Submit new complaint */
async function submitIssue(e) {
    e.preventDefault();

    const lat = document.getElementById("lat")?.value;
    const lng = document.getElementById("lng")?.value;

    if (!lat || !lng) {
        showToast("Please set a location on the map first.", "warning");
        return;
    }

    const formData = new FormData();
    formData.append("title", document.getElementById("title").value);
    formData.append("description", document.getElementById("description").value);
    formData.append("category", document.getElementById("category").value);
    formData.append("type", document.getElementById("type").value);
    formData.append("lat", lat);
    formData.append("lng", lng);
    formData.append("address", document.getElementById("address").value);
    formData.append("ward", document.getElementById("ward").value);

    const imgFile = document.getElementById("image")?.files[0];
    if (imgFile) {
        formData.append("image", imgFile);
    }

    try {
        const res = await fetch("/api/issues", {
            method: "POST",
            body: formData
        });
        const data = await res.json();

        if (data.success) {
            const issueId = data.data._id;

            // Emergency declaration
            const emergCheckbox = document.getElementById("isEmergency");
            if (emergCheckbox && emergCheckbox.checked) {
                const emergCategory = document.getElementById("emergencyCategory")?.value || "GENERAL";
                try {
                    await fetch(`/api/issues/${issueId}/declare-emergency`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ emergency_category: emergCategory })
                    });
                    showToast("Emergency declared!", "danger");
                } catch (emergErr) {
                    console.error("Emergency declaration failed", emergErr);
                }
            }

            showToast("Complaint submitted successfully!", "success");

            // Show AI feedback panel
            const ai = data.data.ai_analysis || {};
            const aiPanel = document.getElementById("aiPanel");
            const aiResults = document.getElementById("aiResults");

            if (aiPanel && aiResults) {
                const visionStatus = ai.image_analysis_available
                    ? "Image analysis completed"
                    : "Image analysis unavailable; text analysis used";
                aiResults.innerHTML = `
                    <div><strong>Category Detected:</strong> ${ai.category || 'other'}</div>
                    <div><strong>Issue Type:</strong> ${ai.type || 'other'}</div>
                    <div><strong>Severity Level:</strong>
                        <span class="badge ${ai.severity === 'critical' ? 'badge-critical' : 'badge-severity'}">
                            ${ai.severity || 'medium'}
                        </span>
                    </div>
                    <div><strong>Assigned Department:</strong> ${ai.department || 'roads'}</div>
                    <div><strong>AI Confidence:</strong> ${ai.confidence_type === 'heuristic' ? 'Heuristic fallback' : `${Math.round((ai.confidence || 0) * 100)}%`}</div>
                    <div><strong>Vision Status:</strong> ${visionStatus}</div>
                    <div><strong>Explanation:</strong> ${ai.explanation || 'No explanation available.'}</div>
                `;
                aiPanel.style.display = "block";
            }

            document.getElementById("reportForm").reset();
            const emergContainer = document.getElementById("emergencyCategoryContainer");
            if (emergContainer) emergContainer.style.display = "none";

            // Keep the last known location after reset
            updateCoords(lat, lng);

            loadMyIssues();
            loadPublicIssues();
        } else {
            showToast(data.error?.message || "Failed to submit issue.", "danger");
        }
    } catch (err) {
        console.error(err);
        showToast("Server communication error.", "danger");
    }
}

function dismissAiPanel() {
    const panel = document.getElementById("aiPanel");
    if (panel) panel.style.display = "none";
}

async function loadMyIssues() {
    try {
        const res = await fetch("/api/issues");
        const data = await res.json();
        if (data.success) {
            allCitizenIssues = data.data || [];
            renderCitizenIssues();
        }
    } catch (err) {
        console.error("Failed to load issues:", err);
    }
}

function renderCitizenIssues() {
    const listEl = document.getElementById("trackerList");
    if (!listEl) return;
    listEl.innerHTML = "";

    const filtered = allCitizenIssues.filter(item =>
        citizenFilter ? citizenFilter.filterItem(item) : true
    );
    if (citizenFilter) {
        citizenFilter.updateBadge(filtered.length, allCitizenIssues.length);
    }

    if (filtered.length === 0) {
        listEl.innerHTML = `
            <div class="empty-state">
                <i class="fa-solid fa-inbox empty-state-icon"></i>
                <div>No reports match the selected filters.</div>
            </div>`;
        return;
    }

    filtered.forEach(issue => {
        const isVerification = issue.status === "citizen_verification";
        const sev = (issue.severity || 'medium').toLowerCase();
        let badgeClass = 'badge-medium';
        if (sev === 'critical') badgeClass = 'badge-critical';
        else if (sev === 'high') badgeClass = 'badge-high';
        else if (sev === 'low') badgeClass = 'badge-low';

        const card = document.createElement("div");
        card.className = "issue-card";
        card.innerHTML = `
            <div style="display: flex; justify-content: space-between; align-items: center; gap: 0.5rem;">
                <strong style="font-size: 0.95rem; color: var(--sc-text);">${issue.title}</strong>
                <div style="display: flex; gap: 0.35rem;">
                    <span class="badge ${badgeClass}">${issue.severity}</span>
                    <span class="badge badge-status">${issue.status}</span>
                </div>
            </div>
            <div style="font-size: 0.85rem; color: var(--sc-muted);">${issue.description}</div>
            <div style="font-size: 0.82rem; color: var(--sc-muted); display: flex; align-items: center; gap: 0.4rem;">
                <i class="fa-solid fa-location-dot" style="color: var(--sc-primary)"></i>
                ${issue.address || 'Address not specified'}
            </div>
            ${isVerification ? `
                <div style="display: flex; gap: 0.5rem; margin-top: 0.5rem;">
                    <button onclick="verifyResolution('${issue._id}', true)" class="btn btn-primary" style="flex: 1; padding: 0.4rem; font-size: 0.8rem;">
                        <i class="fa-solid fa-thumbs-up"></i> Fixed
                    </button>
                    <button onclick="verifyResolution('${issue._id}', false)" class="btn btn-secondary" style="flex: 1; padding: 0.4rem; font-size: 0.8rem; border-color: var(--sc-critical-border); color: var(--sc-critical-text);">
                        <i class="fa-solid fa-rotate-left"></i> Reopen
                    </button>
                </div>
            ` : ''}
        `;
        listEl.appendChild(card);
    });
}

async function verifyResolution(issueId, resolved) {
    const feedback = prompt(
        resolved ? "Please leave short feedback (optional):" : "Why was the issue not fixed? (required):"
    );
    if (!resolved && !feedback) {
        showToast("Feedback is required to reopen complaints.", "warning");
        return;
    }

    try {
        const res = await fetch(`/api/issues/${issueId}/citizen-verify`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ resolved, feedback: feedback || "" })
        });
        const data = await res.json();
        if (data.success) {
            showToast(resolved ? "Complaint closed successfully!" : "Complaint reopened successfully.", "success");
            loadMyIssues();
            if (resolved) {
                setTimeout(() => {
                    const stars = prompt("Please rate the repair quality (1 to 5 stars):");
                    if (stars && parseInt(stars) >= 1 && parseInt(stars) <= 5) {
                        submitIssueFeedback(issueId, parseInt(stars));
                    }
                }, 500);
            }
        } else {
            showToast(data.error?.message || "Action failed.", "danger");
        }
    } catch (err) {
        showToast("Server communication error.", "danger");
    }
}

function toggleEmergencyCategory() {
    const isEmerg = document.getElementById("isEmergency")?.checked;
    const container = document.getElementById("emergencyCategoryContainer");
    if (container) {
        container.style.display = isEmerg ? "block" : "none";
    }
}

function updateLanguagePlaceholder() {
    const lang = document.getElementById("language")?.value;
    const desc = document.getElementById("description");
    if (!desc) return;

    if (lang === "kannada") {
        desc.placeholder = "ನಿಮ್ಮ ಸಮಸ್ಯೆಯನ್ನು ಇಲ್ಲಿ ವಿವರಿಸಿ...";
    } else if (lang === "hindi") {
        desc.placeholder = "अपनी समस्या यहाँ बताएं...";
    } else if (lang === "tamil") {
        desc.placeholder = "உங்கள் பிரச்சனையை இங்கே விவரிக்கவும்...";
    } else if (lang === "telugu") {
        desc.placeholder = "మీ సమస్యను ఇక్కడ వివరించండి...";
    } else {
        desc.placeholder = "Describe the issue here...";
    }
}

async function loadPublicIssues() {
    try {
        const res = await fetch("/api/public/map");
        const data = await res.json();
        if (!data.success || !map) return;

        publicMarkers.forEach(m => map.removeLayer(m));
        publicMarkers = [];

        (data.data || []).forEach(issue => {
            const coords = issue.location?.coordinates;
            if (!coords || coords.length < 2) return;

            const lat = coords[1];
            const lng = coords[0];

            let markerColor = '#38bdf8';
            if (issue.severity === 'critical') markerColor = '#ef4444';
            else if (issue.severity === 'high') markerColor = '#f59e0b';

            const cMarker = L.circleMarker([lat, lng], {
                radius: 8 + Math.min(issue.confirmation_count || 0, 10),
                color: markerColor,
                fillColor: markerColor,
                fillOpacity: 0.5
            }).addTo(map);

            cMarker.bindPopup(`
                <div style="font-family: 'Plus Jakarta Sans', sans-serif;">
                    <h4 style="margin:0 0 5px 0; color: #1e293b;">${(issue.category || '').toUpperCase()}</h4>
                    <p style="margin:0; font-size:0.8rem; color:#64748b;">Status: <strong>${issue.status}</strong></p>
                    <p style="margin:0 0 8px 0; font-size:0.8rem; color:#64748b;">
                        Confirmations: <strong>${issue.confirmation_count || 0}</strong>
                    </p>
                    <button onclick="confirmPublicIssue('${issue._id}')" class="btn btn-primary"
                            style="padding: 0.3rem 0.6rem; font-size: 0.75rem;">
                        <i class="fa-solid fa-eye"></i> I see this too
                    </button>
                </div>
            `);
            publicMarkers.push(cMarker);
        });
    } catch (err) {
        console.error("Failed to load public markers", err);
    }
}

async function confirmPublicIssue(issueId) {
    const note = prompt("Add a note (optional):");
    if (note === null) return;

    try {
        const res = await fetch(`/api/issues/${issueId}/confirm`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ note: note || "" })
        });
        const data = await res.json();
        if (data.success) {
            showToast("Issue confirmation logged! Thank you.", "success");
            map.closePopup();
            loadPublicIssues();
        } else {
            showToast(data.error?.message || "Failed to confirm issue.", "danger");
        }
    } catch (err) {
        showToast("Communication error.", "danger");
    }
}

async function submitIssueFeedback(issueId, rating) {
    const feedbackText = prompt("Any comments about the fix? (optional):");
    if (feedbackText === null) return;

    try {
        const res = await fetch(`/api/issues/${issueId}/feedback`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ rating, feedback_text: feedbackText })
        });
        const data = await res.json();
        if (data.success) {
            showToast("Thank you for your feedback!", "success");
            loadMyIssues();
        } else {
            showToast(data.error?.message || "Failed to submit rating.", "danger");
        }
    } catch (err) {
        showToast("Communication error.", "danger");
    }
}
