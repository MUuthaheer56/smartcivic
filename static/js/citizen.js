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
    const statusEl = document.getElementById("location-status");

    if (window.isSecureContext === false && window.location.hostname !== "localhost" && window.location.hostname !== "127.0.0.1") {
        const msg = "Geolocation requires HTTPS. Drag or click the map pin manually.";
        if (typeof showToast === "function") showToast(msg, "warning");
        if (statusEl) statusEl.textContent = "Manual pin drop mode (HTTPS required)";
        return;
    }

    if (!navigator.geolocation) {
        const msg = "Geolocation is not supported by your browser. Please drop pin manually.";
        if (typeof showToast === "function") showToast(msg, "warning");
        if (statusEl) statusEl.textContent = "Manual pin drop mode active";
        return;
    }

    navigator.geolocation.getCurrentPosition(
        (pos) => {
            const lat = pos.coords.latitude;
            const lng = pos.coords.longitude;

            if (typeof map !== 'undefined' && map && typeof marker !== 'undefined' && marker) {
                map.setView([lat, lng], 16);
                marker.setLatLng([lat, lng]);
            }
            updateCoords(lat, lng);
            reverseGeocode(lat, lng);

            if (typeof showToast === "function") {
                showToast("Location detected successfully", "success");
            }
            if (statusEl) statusEl.textContent = "GPS location detected";
        },
        (err) => {
            let msg = "Could not detect location. Please click or drag the map pin manually.";
            if (err.code === 1) {
                msg = "Location permission denied. Please click or drag the map pin manually.";
            } else if (err.code === 2) {
                msg = "Location signal unavailable. Please click or drag the map pin manually.";
            } else if (err.code === 3) {
                msg = "Location request timed out. Please click or drag the map pin manually.";
            }
            console.warn("GPS error:", err.message);
            if (typeof showToast === "function") {
                showToast(msg, "warning");
            }
            if (statusEl) statusEl.textContent = "Manual pin drop mode active";
        },
        {
            enableHighAccuracy: true,
            timeout: 10000,
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

// CTVE state — stored so the upload/confirm functions can access it
let _ctveComplaintId = null;
let _ctveData = null;

function severityLabel(score) {
    if (typeof score === 'string') return score;
    if (score >= 0.85) return 'Critical';
    if (score >= 0.60) return 'High';
    if (score >= 0.35) return 'Medium';
    return 'Low';
}

/**
 * Call this INSTEAD of showing the normal success message
 * when the complaint submission response has ctve_triggered=true.
 *
 * @param {string} complaintId  - ID of the just-created complaint
 * @param {object} ctveData     - {ctve_message, signals: {text_severity, image_severity}}
 */
function showCtveModal(complaintId, ctveData) {
    _ctveComplaintId = complaintId;
    _ctveData = ctveData;

    // Fill in the dynamic message
    const msgEl = document.getElementById('ctve-message-text');
    if (msgEl) msgEl.textContent = ctveData.ctve_message || 'Please clarify the evidence.';

    // Show evidence comparison row if image was present
    const ts = ctveData.signals?.text_severity;
    const is = ctveData.signals?.image_severity;
    if (ts !== null && ts !== undefined && is !== null && is !== undefined) {
        const row = document.getElementById('ctve-evidence-row');
        if (row) row.style.display = 'flex';
        const tsEl = document.getElementById('ctve-text-severity');
        const isEl = document.getElementById('ctve-image-severity');
        if (tsEl) tsEl.textContent = severityLabel(ts);
        if (isEl) isEl.textContent = severityLabel(is);
    }

    // Show modal
    const modal = document.getElementById('ctve-modal');
    if (modal) modal.style.display = 'flex';
}

async function handleCtvePhotoUpload(input) {
    if (!input.files || !input.files[0]) return;
    const file = input.files[0];

    setCtveStatus('Uploading photo…', 'info');

    const formData = new FormData();
    formData.append('photo', file);
    formData.append('complaint_id', _ctveComplaintId);
    formData.append('ctve_response', 'photo_uploaded');

    try {
        const authFetch = (window.SmartCivicAuth && typeof window.SmartCivicAuth.fetch === 'function')
            ? window.SmartCivicAuth.fetch.bind(window.SmartCivicAuth)
            : fetch;
        const res = await authFetch(
            `/api/issues/${_ctveComplaintId}/ctve-response`,
            { method: 'POST', body: formData }
        );
        const data = await res.json();
        if (res.ok) {
            setCtveStatus('Photo received — your complaint has been updated.', 'success');
            setTimeout(() => { window.location.href = '/citizen/dashboard'; }, 1800);
        } else {
            setCtveStatus(data.error || 'Upload failed. Please try again.', 'error');
        }
    } catch {
        setCtveStatus('Network error. Please try again.', 'error');
    }
}

async function confirmCtveOriginal() {
    setCtveStatus('Confirming…', 'info');

    try {
        const authFetch = (window.SmartCivicAuth && typeof window.SmartCivicAuth.fetch === 'function')
            ? window.SmartCivicAuth.fetch.bind(window.SmartCivicAuth)
            : fetch;
        const res = await authFetch(
            `/api/issues/${_ctveComplaintId}/ctve-response`,
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ctve_response: 'description_confirmed', complaint_id: _ctveComplaintId }),
            }
        );
        const data = await res.json();
        if (res.ok) {
            setCtveStatus('Confirmed — your complaint has been queued for officer review.', 'success');
            setTimeout(() => { window.location.href = '/citizen/dashboard'; }, 1800);
        } else {
            setCtveStatus(data.error || 'Error. Please try again.', 'error');
        }
    } catch {
        setCtveStatus('Network error. Please try again.', 'error');
    }
}

function setCtveStatus(msg, type) {
    const el = document.getElementById('ctve-status');
    if (!el) return;
    el.style.display = 'block';
    el.textContent = msg;
    const colors = {
        info: { bg: 'rgba(47, 91, 216, 0.12)', color: '#2f5bd8' },
        success: { bg: 'rgba(15, 157, 107, 0.12)', color: '#0f9d6b' },
        error: { bg: 'rgba(209, 38, 74, 0.12)', color: '#d1264a' },
    };
    const c = colors[type] || colors.info;
    el.style.background = c.bg;
    el.style.color = c.color;
}

// Make CTVE functions globally available on window for inline event handlers
window.handleCtvePhotoUpload = handleCtvePhotoUpload;
window.confirmCtveOriginal = confirmCtveOriginal;
window.showCtveModal = showCtveModal;

/** Submit new complaint */
async function submitIssue(e) {
    e.preventDefault();

    const submitBtn = e.target.querySelector('button[type="submit"]') || document.querySelector('#reportForm button[type="submit"]');
    if (submitBtn && submitBtn.disabled) return;
    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.dataset.originalText = submitBtn.innerHTML;
        submitBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Submitting...';
    }

    const lat = document.getElementById("lat")?.value;
    const lng = document.getElementById("lng")?.value;

    if (!lat || !lng) {
        showToast("Please set a location on the map first.", "warning");
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = submitBtn.dataset.originalText || 'Submit';
        }
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
            const issueId = data.issue_id || (data.data && data.data._id) || (data.data && data.data.issue_id);

            // Check if CTVE evidence disagreement was triggered
            if (data.ctve_triggered || (data.data && data.data.ctve_triggered)) {
                showCtveModal(issueId, {
                    ctve_message: data.ctve_message || (data.data && data.data.ctve_message),
                    signals: data.signals || (data.data && data.data.signals) || {}
                });
                return;
            }

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
            const ai = data.data.ai_analysis || data.ai_prediction || {};
            const imgDets = (ai.image_detections && ai.image_detections.length > 0)
                ? ai.image_detections
                : (data.data.image_detections || (data.data.visual_evidence?.defect_name ? [data.data.visual_evidence.defect_name] : []));
            const hasDetectedDefects = imgDets.length > 0;
            const detectedDefectsStr = hasDetectedDefects ? imgDets.join(', ') : (ai.type && ai.type !== 'other' ? ai.type : 'Road defect verified');
            const aiPanel = document.getElementById("aiPanel");
            const aiResults = document.getElementById("aiResults");

            if (aiPanel && aiResults) {
                const visionStatus = ai.image_analysis_available || hasDetectedDefects
                    ? "Image analysis completed"
                    : (ai.image_analysis_message || "Image analysis unavailable, your report was still recorded");
                const esc = window.escapeHtml || (s => String(s || ''));
                aiResults.innerHTML = `
                    ${hasDetectedDefects ? `
                    <div class="ai-image-detection-callout detected">
                        <div class="ai-callout-header">
                            <i class="fa-solid fa-brain" style="color: var(--jewel-emerald, #0f9d6b);"></i>
                            <span>AI Vision Model Detection:</span>
                            <span class="ai-badge-pill">Detected in Photo</span>
                        </div>
                        <div style="font-size: 0.95rem; font-weight: 700; color: var(--sc-text); margin-top: 0.2rem;">
                            🎯 Defect Identified: <span style="color: var(--jewel-emerald, #0f9d6b);">${esc(detectedDefectsStr)}</span>
                        </div>
                        <div class="ai-model-tag">Model: YOLOv8 ONNX (road_damage_v1) • Automated Severity Calibration Applied</div>
                    </div>
                    ` : (imgFile ? `
                    <div class="ai-image-detection-callout">
                        <div class="ai-callout-header">
                            <i class="fa-solid fa-camera"></i>
                            <span>Photo Evidence Attached</span>
                        </div>
                        <div style="font-size: 0.85rem; color: var(--sc-muted);">Uploaded photo successfully linked and verified.</div>
                    </div>
                    ` : '')}
                    <div><strong>Category Detected:</strong> ${esc(ai.category || 'other')}</div>
                    <div><strong>Issue Type:</strong> ${esc(ai.type || 'other')}</div>
                    <div><strong>Severity Level:</strong>
                        <span class="badge ${ai.severity === 'critical' ? 'badge-critical' : 'badge-severity'}">
                            ${esc(ai.severity || 'medium')}
                        </span>
                    </div>
                    <div><strong>Assigned Department:</strong> ${esc(ai.department || 'roads')}</div>
                    <div><strong>AI Confidence:</strong> ${ai.confidence_type === 'heuristic' ? 'Heuristic fallback' : `${Math.round((ai.confidence || 0) * 100)}%`}</div>
                    <div><strong>Vision Status:</strong> ${esc(visionStatus)}</div>
                    <div><strong>Explanation:</strong> ${esc(ai.explanation || 'Visual evidence processed and integrated into triage.')}</div>
                `;
                aiPanel.style.display = "block";
            }

            document.getElementById("reportForm").reset();
            const emergContainer = document.getElementById("emergencyCategoryContainer");
            if (emergContainer) emergContainer.style.display = "none";

            // Keep the last known location after reset
            updateCoords(lat, lng);

            // Phase 2: Query and render similar report suggestion if available
            checkAndShowDuplicateSuggestions(issueId);

            loadMyIssues();
            loadPublicIssues();
        } else {
            showToast(data.error?.message || "Failed to submit issue.", "danger");
        }
    } catch (err) {
        console.error(err);
        showToast("Server communication error.", "danger");
    } finally {
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = submitBtn.dataset.originalText || 'Submit';
        }
    }
}

function dismissAiPanel() {
    const panel = document.getElementById("aiPanel");
    if (panel) panel.style.display = "none";
}

async function loadMyIssues() {
    const listEl = document.getElementById("trackerList");
    if (listEl && (!allCitizenIssues || allCitizenIssues.length === 0)) {
        if (typeof window.renderLoading === "function") {
            window.renderLoading(listEl, "Loading your civic reports...");
        }
    }
    try {
        const fetchFn = window.api || window.fetch;
        const res = await fetchFn("/api/issues");
        const data = (res && typeof res.json === "function" && !(res instanceof Response)) ? res : (res.data ? res : await res.json());
        if (data && data.success) {
            allCitizenIssues = data.data || [];
            renderCitizenIssues();
        } else {
            if (listEl && typeof window.renderErrorRetry === "function") {
                window.renderErrorRetry(listEl, "Failed to load reports.", () => loadMyIssues());
            }
        }
    } catch (err) {
        console.error("Failed to load issues:", err);
        if (listEl && typeof window.renderErrorRetry === "function") {
            window.renderErrorRetry(listEl, "Failed to load reports. Check your connection.", () => loadMyIssues());
        }
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

        const esc = window.escapeHtml || (s => s ? String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#039;') : '');

        // Resolve uploaded image
        const imgObj = issue.image;
        const imgUrl = (imgObj && typeof imgObj === 'object' ? imgObj.url : (typeof imgObj === 'string' ? imgObj : null))
            || (issue.images && issue.images[0] ? (issue.images[0].url || issue.images[0]) : null)
            || (issue.thumbnail_url && !issue.thumbnail_url.includes('placeholder') ? issue.thumbnail_url : null);

        // Resolve AI detections
        const imgDets = issue.image_detections || (issue.ai_analysis && issue.ai_analysis.image_detections) || [];
        const visDefect = issue.visual_evidence?.defect_name;
        const defectName = imgDets.length > 0 ? imgDets.join(', ') : (visDefect || (issue.category === 'road' && issue.type ? issue.type : null));
        const hasAiDetection = !!defectName && (imgDets.length > 0 || !!visDefect || issue.ai_analysis?.image_analysis_available);

        const card = document.createElement("div");
        card.className = "issue-card";
        card.innerHTML = `
            <div style="display: flex; justify-content: space-between; align-items: center; gap: 0.5rem;">
                <strong style="font-size: 0.95rem; color: var(--sc-text);">${esc(issue.title)}</strong>
                <div style="display: flex; gap: 0.35rem;">
                    <span class="badge ${badgeClass}">${esc(issue.severity)}</span>
                    <span class="badge badge-status">${esc(issue.status)}</span>
                </div>
            </div>
            <div style="font-size: 0.85rem; color: var(--sc-muted);">${esc(issue.description)}</div>
            <div style="font-size: 0.82rem; color: var(--sc-muted); display: flex; align-items: center; gap: 0.4rem;">
                <i class="fa-solid fa-location-dot" style="color: var(--sc-primary)"></i>
                ${esc(issue.address || 'Address not specified')}
            </div>

            ${imgUrl ? `
                <div class="card-image-preview">
                    <img src="${esc(imgUrl)}" alt="Uploaded Complaint Photo" loading="lazy" />
                    ${hasAiDetection ? `
                    <div class="card-ai-vision-overlay">
                        <i class="fa-solid fa-robot" style="color: #6ee7b7;"></i>
                        <span>AI Detected in Image: <strong>${esc(defectName)}</strong></span>
                    </div>
                    ` : `
                    <div class="card-ai-vision-overlay">
                        <i class="fa-solid fa-camera"></i>
                        <span>Uploaded Evidence Photo</span>
                    </div>
                    `}
                </div>
            ` : (hasAiDetection ? `
                <div class="card-ai-vision-tag detected">
                    <i class="fa-solid fa-robot"></i>
                    <span>AI Detected: <strong>${esc(defectName)}</strong></span>
                </div>
            ` : '')}

            ${isVerification ? `
                <div style="display: flex; gap: 0.5rem; margin-top: 0.5rem;">
                    <button onclick="verifyResolution('${encodeURIComponent(issue._id)}', true)" class="btn btn-primary" style="flex: 1; padding: 0.4rem; font-size: 0.8rem;">
                        <i class="fa-solid fa-thumbs-up"></i> Fixed
                    </button>
                    <button onclick="verifyResolution('${encodeURIComponent(issue._id)}', false)" class="btn btn-secondary" style="flex: 1; padding: 0.4rem; font-size: 0.8rem; border-color: var(--sc-critical-border); color: var(--sc-critical-text);">
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

            let markerColor = '#2f5bd8';
            if (issue.severity === 'critical') markerColor = '#d1264a';
            else if (issue.severity === 'high') markerColor = '#e0701a';
            else if (issue.severity === 'medium') markerColor = '#d99a1a';
            else if (issue.severity === 'low') markerColor = '#0f9d6b';

            const cMarker = L.circleMarker([lat, lng], {
                radius: 8 + Math.min(issue.confirmation_count || 0, 10),
                color: '#c9a227',
                weight: 1.5,
                fillColor: markerColor,
                fillOpacity: 0.75
            }).addTo(map);

            cMarker.bindPopup(`
                <div style="font-family: 'Plus Jakarta Sans', sans-serif; padding: 4px;">
                    <h4 style="margin:0 0 5px 0; color: #0b1437; font-family: 'Playfair Display', serif; font-weight:700;">${(issue.category || '').toUpperCase()}</h4>
                    <p style="margin:0; font-size:0.8rem; color: #5b5a72;">Status: <strong>${issue.status}</strong></p>
                    <p style="margin:0 0 8px 0; font-size:0.8rem; color: #5b5a72;">
                        Confirmations: <strong>${issue.confirmation_count || 0}</strong>
                    </p>
                    <button onclick="confirmPublicIssue('${issue._id}')" class="btn btn-primary"
                            style="padding: 0.35rem 0.75rem; font-size: 0.78rem;">
                        <i class="fa-solid fa-eye" style="color: var(--accent-gold);"></i> I see this too
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
        showToast("Error recording feedback.", "danger");
    }
}

async function checkAndShowDuplicateSuggestions(issueId) {
    if (!issueId) return;
    try {
        const res = await fetch(`/api/issues/${issueId}/duplicate-suggestions`);
        if (!res.ok) return;
        const data = await res.json();
        if (data.suggestions && data.suggestions.length > 0) {
            showDuplicateSuggestionCard(issueId, data.suggestions[0]);
        }
    } catch (e) {
        console.debug("Duplicate suggestions fetch skipped:", e);
    }
}

function showDuplicateSuggestionCard(sourceIssueId, candidate) {
    const container = document.getElementById("aiPanel") || document.getElementById("citizenAlertArea");
    if (!container) return;

    // Remove existing card if any
    const existing = document.getElementById("duplicate-suggestion-card");
    if (existing) existing.remove();

    const esc = window.escapeHtml || (s => s ? String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#039;') : '');
    const card = document.createElement("div");
    card.id = "duplicate-suggestion-card";
    card.style.cssText = "background: rgba(201, 162, 39, 0.12); border: 1px solid var(--accent-gold, #c9a227); border-radius: var(--radius-md, 12px); padding: 1.25rem; margin-top: 1rem; box-shadow: var(--shadow-sm);";
    card.innerHTML = `
        <h5 style="color: var(--accent-gold-dark, #a47e0f); font-family: var(--font-display); font-weight: 700; margin-bottom: 8px; font-size: 1.05rem;"><i class="fa fa-circle-exclamation"></i> Similar report nearby. Same problem?</h5>
        <p style="margin-bottom: 8px; color: var(--text-secondary); font-size: 0.9rem;">
            A similar issue was found <strong>${Number(candidate.distance_meters || 0)}m away</strong> (${Math.round((candidate.score || 0) * 100)}% match):<br>
            <em>"${esc(candidate.candidate_title)}"</em>
        </p>
        <div style="display:flex; gap:10px; align-items:center;">
            <button class="btn btn-sm btn-primary" id="btn-support-duplicate" style="padding: 6px 14px; font-weight: 600;">
                <i class="fa fa-thumbs-up" style="color: var(--accent-gold);"></i> Yes, support this existing report
            </button>
            <button class="btn btn-sm btn-secondary" id="btn-reject-duplicate" style="padding: 6px 14px; font-weight: 600;">
                No, this is different
            </button>
        </div>
        <div id="duplicate-feedback-msg" style="display:none; margin-top:8px; font-weight:600; color: var(--jewel-emerald, #0f9d6b); font-size:0.9rem;"></div>
    `;

    container.appendChild(card);

    document.getElementById("btn-support-duplicate")?.addEventListener("click", async () => {
        try {
            const resp = await fetch(`/api/issues/${sourceIssueId}/duplicate-confirm`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ target_issue_id: candidate.candidate_issue_id, action: "confirm" })
            });
            const fb = document.getElementById("duplicate-feedback-msg");
            if (fb) {
                fb.style.display = "block";
                fb.textContent = "Thank you! Your support was added to the existing report to raise its priority.";
            }
            document.getElementById("btn-support-duplicate").style.display = "none";
            document.getElementById("btn-reject-duplicate").style.display = "none";
        } catch (err) {
            console.error("Duplicate confirm error:", err);
        }
    });

    document.getElementById("btn-reject-duplicate")?.addEventListener("click", async () => {
        try {
            await fetch(`/api/issues/${sourceIssueId}/duplicate-confirm`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ target_issue_id: candidate.candidate_issue_id, action: "reject" })
            });
            card.remove();
        } catch (err) {
            card.remove();
        }
    });
}
