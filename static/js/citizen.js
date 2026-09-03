/**
 * SmartCivic+ — Citizen Dashboard JS
 */
let map;
let marker;
let allCitizenIssues = [];
let citizenFilter;

document.addEventListener("DOMContentLoaded", () => {
    initMap();
    citizenFilter = new SmartCivicFilter({
        containerId: 'filterBar',
        onFilterChange: () => renderCitizenIssues()
    });
    loadMyIssues();
    
    document.getElementById("reportForm").addEventListener("submit", submitIssue);
});

function initMap() {
    // Default location: Bangalore (12.9716, 77.5946)
    map = L.map('map').setView([12.9716, 77.5946], 13);
    
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '© OpenStreetMap contributors'
    }).addTo(map);
    
    // Add default marker
    marker = L.marker([12.9716, 77.5946], { draggable: true }).addTo(map);
    updateCoords(12.9716, 77.5946);
    
    marker.on('dragend', function (e) {
        const position = marker.getLatLng();
        updateCoords(position.lat, position.lng);
        reverseGeocode(position.lat, position.lng);
    });
    
    map.on('click', function (e) {
        marker.setLatLng(e.latlng);
        updateCoords(e.latlng.lat, e.latlng.lng);
        reverseGeocode(e.latlng.lat, e.latlng.lng);
    });
}

function updateCoords(lat, lng) {
    document.getElementById("lat").value = lat;
    document.getElementById("lng").value = lng;
}

async function reverseGeocode(lat, lng) {
    try {
        const res = await fetch(`https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lng}`, {
            headers: { 'Accept-Language': 'en' }
        });
        const data = await res.json();
        if (data && data.display_name) {
            document.getElementById("address").value = data.display_name;
            
            // Guess ward/suburb
            const address = data.address || {};
            const ward = address.suburb || address.neighbourhood || address.quarter || address.city_district || "Ward 1";
            document.getElementById("ward").value = ward;
        }
    } catch (err) {
        console.error("Reverse geocoding failed: ", err);
    }
}

async function submitIssue(e) {
    e.preventDefault();
    
    const formData = new FormData();
    formData.append("title", document.getElementById("title").value);
    formData.append("description", document.getElementById("description").value);
    formData.append("category", document.getElementById("category").value);
    formData.append("type", document.getElementById("type").value);
    formData.append("lat", document.getElementById("lat").value);
    formData.append("lng", document.getElementById("lng").value);
    formData.append("address", document.getElementById("address").value);
    formData.append("ward", document.getElementById("ward").value);
    
    const imgFile = document.getElementById("image").files[0];
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
            
            // If emergency is checked, declare it
            const isEmerg = document.getElementById("isEmergency").checked;
            if (isEmerg) {
                const emergCategory = document.getElementById("emergencyCategory").value;
                try {
                    await fetch(`/api/issues/${issueId}/declare-emergency`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ emergency_category: emergCategory })
                    });
                    showToast("Emergency state declared!", "danger");
                } catch (emergErr) {
                    console.error("Emergency declaration failed", emergErr);
                }
            }
            
            showToast("Complaint submitted successfully!", "success");
            
            // Show AI Feedback Panel
            const ai = data.data.ai_analysis || {};
            const aiPanel = document.getElementById("aiPanel");
            const aiResults = document.getElementById("aiResults");
            
            aiResults.innerHTML = `
                <div><strong>Category Detected:</strong> ${ai.category || 'other'}</div>
                <div><strong>Issue Type:</strong> ${ai.type || 'other'}</div>
                <div><strong>Severity Level:</strong> <span class="badge ${ai.severity === 'critical' ? 'badge-critical' : 'badge-severity'}">${ai.severity || 'medium'}</span></div>
                <div><strong>Assigned Department:</strong> ${ai.department || 'roads'}</div>
                <div><strong>AI Confidence Rate:</strong> ${Math.round((ai.confidence || 0) * 100)}%</div>
            `;
            
            aiPanel.style.display = "block";
            
            document.getElementById("reportForm").reset();
            document.getElementById("emergencyCategoryContainer").style.display = "none";
            loadMyIssues();
            loadPublicIssues(); // Refresh public markers
        } else {
            showToast(data.error.message || "Failed to submit issue.", "danger");
        }
    } catch (err) {
        showToast("Server communication error.", "danger");
    }
}

function dismissAiPanel() {
    document.getElementById("aiPanel").style.display = "none";
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
        console.error("Failed to load issues: ", err);
    }
}

function renderCitizenIssues() {
    const listEl = document.getElementById("trackerList");
    if (!listEl) return;
    listEl.innerHTML = "";
    
    const filtered = allCitizenIssues.filter(item => citizenFilter ? citizenFilter.filterItem(item) : true);
    if (citizenFilter) citizenFilter.updateBadge(filtered.length, allCitizenIssues.length);
    
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
                <strong style="font-size: 0.95rem; color: #ffffff;">${issue.title}</strong>
                <div style="display: flex; gap: 0.35rem;">
                    <span class="badge ${badgeClass}">${issue.severity}</span>
                    <span class="badge badge-status">${issue.status}</span>
                </div>
            </div>
            <div style="font-size: 0.85rem; color: var(--sc-muted);">${issue.description}</div>
            <div style="font-size: 0.82rem; color: var(--sc-muted); display: flex; align-items: center; gap: 0.4rem;">
                <i class="fa-solid fa-location-dot" style="color: var(--sc-primary)"></i> ${issue.address || 'Address not specified'}
            </div>
            
            ${isVerification ? `
                <div style="display: flex; gap: 0.5rem; margin-top: 0.5rem;">
                    <button onclick="verifyResolution('${issue._id}', true)" class="btn btn-primary" style="flex: 1; padding: 0.4rem; font-size: 0.8rem;"><i class="fa-solid fa-thumbs-up"></i> Fixed</button>
                    <button onclick="verifyResolution('${issue._id}', false)" class="btn btn-secondary" style="flex: 1; padding: 0.4rem; font-size: 0.8rem; border-color: var(--sc-critical-border); color: var(--sc-critical-text);"><i class="fa-solid fa-rotate-left"></i> Reopen</button>
                </div>
            ` : ''}
        `;
        listEl.appendChild(card);
    });
}

async function verifyResolution(issueId, resolved) {
    const feedback = prompt(resolved ? "Please leave short feedback (optional):" : "Why was the issue not fixed? (required):");
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
            showToast(data.error.message || "Action failed.", "danger");
        }
    } catch (err) {
        showToast("Server communication error.", "danger");
    }
}

function toggleEmergencyCategory() {
    const isEmerg = document.getElementById("isEmergency").checked;
    document.getElementById("emergencyCategoryContainer").style.display = isEmerg ? "block" : "none";
}

function updateLanguagePlaceholder() {
    const lang = document.getElementById("language").value;
    const desc = document.getElementById("description");
    
    if (lang === "kannada") {
        desc.placeholder = "ನಿಮ್ಮ ಸಮಸ್ಯೆಯನ್ನು ಇಲ್ಲಿ ವಿವರಿಸಿ...";
    } else if (lang === "hindi") {
        desc.placeholder = "अपनी समस्या यहाँ बताएं...";
    } else if (lang === "tamil") {
        desc.placeholder = "உங்கள் பிரச்சனೆಯನ್ನು இங்கே விவரிக்கவும்...";
    } else if (lang === "telugu") {
        desc.placeholder = "మీ ಸಮಸ್ಯೆನು ఇక్కడ వివరించండి...";
    } else {
        desc.placeholder = "Describe the issue here...";
    }
}

let publicMarkers = [];
async function loadPublicIssues() {
    try {
        const res = await fetch("/api/public/map");
        const data = await res.json();
        if (data.success) {
            // Clear existing public markers
            publicMarkers.forEach(m => map.removeLayer(m));
            publicMarkers = [];
            
            data.data.forEach(issue => {
                const coords = issue.location.coordinates;
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
                
                const popupContent = `
                    <div style="font-family: 'Plus Jakarta Sans', sans-serif;">
                        <h4 style="margin:0 0 5px 0; color: #1e293b;">${issue.category.toUpperCase()}</h4>
                        <p style="margin:0; font-size:0.8rem; color:#64748b;">Status: <strong>${issue.status}</strong></p>
                        <p style="margin:0; font-size:0.8rem; color:#64748b; margin-bottom: 8px;">Confirmations: <strong>${issue.confirmation_count || 0}</strong></p>
                        <button onclick="confirmPublicIssue('${issue._id}')" class="btn btn-primary" style="padding: 0.3rem 0.6rem; font-size: 0.75rem;"><i class="fa-solid fa-eye"></i> I see this too</button>
                    </div>
                `;
                cMarker.bindPopup(popupContent);
                publicMarkers.push(cMarker);
            });
        }
    } catch (err) {
        console.error("Failed to load public markers", err);
    }
}

async function confirmPublicIssue(issueId) {
    const note = prompt("Add a note (optional):");
    if (note === null) return; // User cancelled
    
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
            showToast(data.error.message || "Failed to confirm issue.", "danger");
        }
    } catch (err) {
        showToast("Communication error.", "danger");
    }
}

// Hook map loading to retrieve public issues
const originalInitMap = initMap;
initMap = function() {
    originalInitMap();
    loadPublicIssues();
};

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
            showToast(data.error.message || "Failed to submit rating.", "danger");
        }
    } catch (err) {
        showToast("Communication error.", "danger");
    }
}
