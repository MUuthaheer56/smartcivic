/**
 * SmartCivic+ — Worker Dashboard JS
 */
let map;
let routeLine;
let markerLayer = L.layerGroup();
let currentWorkerId = ""; // Resolved from active jobs

document.addEventListener("DOMContentLoaded", () => {
    initMap();
    loadMyJobs();
});

function initMap() {
    map = L.map('workerMap').setView([12.9716, 77.5946], 13);
    
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap'
    }).addTo(map);
    
    markerLayer.addTo(map);
}

async function loadMyJobs() {
    try {
        const res = await fetch("/api/worker/jobs");
        const data = await res.json();
        
        if (data.success) {
            const listEl = document.getElementById("jobsList");
            listEl.innerHTML = "";
            
            if (data.data.length === 0) {
                listEl.innerHTML = `<div style="text-align: center; color: var(--text-muted); padding: 2rem;">No active maintenance orders assigned.</div>`;
                return;
            }
            
            // Set current worker ID
            currentWorkerId = data.data[0].worker_id;
            
            data.data.forEach((job, index) => {
                const isActiveJob = job.status === "work_started";
                
                const card = document.createElement("div");
                card.className = `job-card ${isActiveJob ? 'active' : ''}`;
                card.innerHTML = `
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <strong style="font-size: 0.95rem;">Stop #${index + 1}: ${job.title}</strong>
                        <span class="badge ${job.severity === 'critical' ? 'badge-critical' : 'badge-severity'}">${job.severity}</span>
                    </div>
                    <div style="font-size: 0.85rem; color: var(--text-muted);">${job.description}</div>
                    <div style="font-size: 0.85rem; color: var(--text-muted);"><i class="fa-solid fa-location-dot"></i> ${job.address}</div>
                    
                    <div style="display: flex; gap: 0.5rem; margin-top: 0.5rem;">
                        <button onclick="drawRouteTo('${job._id}')" class="btn btn-secondary" style="flex: 1; padding: 0.4rem; font-size: 0.8rem;">
                            <i class="fa-solid fa-location-arrow"></i> Navigate
                        </button>
                        <button onclick="openJobDetail('${job._id}')" class="btn btn-primary" style="flex: 1; padding: 0.4rem; font-size: 0.8rem;">
                            <i class="fa-solid fa-folder-open"></i> Open Detail
                        </button>
                    </div>
                `;
                listEl.appendChild(card);
            });
            
            // Draw optimized daily itinerary route path
            drawItineraryRoute();
        }
    } catch (err) {
        console.error("Job load failed: ", err);
    }
}

async function drawItineraryRoute() {
    if (!currentWorkerId) return;
    
    try {
        const res = await fetch(`/api/map/route?worker_id=${currentWorkerId}`);
        const data = await res.json();
        
        if (data.success && data.data.length > 0) {
            markerLayer.clearLayers();
            if (routeLine) map.removeLayer(routeLine);
            
            const latlngs = [];
            const summary = document.getElementById("routeSummary");
            let totalDist = 0;
            let totalTime = 0;
            
            data.data.forEach((stop, index) => {
                const coords = stop.coords;
                latlngs.push(...stop.polyline);
                
                totalDist += stop.distance_km;
                totalTime += stop.duration_minutes;
                
                // Add marker
                const marker = L.marker([coords[0], coords[1]], {
                    icon: L.divIcon({
                        className: 'custom-div-icon',
                        html: `<div style="background-color: var(--primary); color: white; width: 24px; height: 24px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: 700; border: 2px solid white;">${index + 1}</div>`,
                        iconSize: [24, 24]
                    })
                });
                markerLayer.addLayer(marker);
            });
            
            // Draw polyline route
            routeLine = L.polyline(latlngs, { color: 'var(--primary)', weight: 5, opacity: 0.8 }).addTo(map);
            map.fitBounds(routeLine.getBounds());
            
            summary.innerHTML = `
                <div><strong>Daily Dispatch Route Metrics:</strong></div>
                <div><i class="fa-solid fa-road"></i> Total Drive Distance: ${totalDist.toFixed(1)} km</div>
                <div><i class="fa-solid fa-clock"></i> Est. Route Travel Time: ${Math.round(totalTime)} minutes</div>
            `;
        }
    } catch (err) {
        console.error("Failed to load OSRM optimized path: ", err);
    }
}

async function drawRouteTo(issueId) {
    // Zoom map directly to the task location
    try {
        const res = await fetch(`/api/issues/${issueId}`);
        const data = await res.json();
        if (data.success && data.data.location?.coordinates) {
            const coords = data.data.location.coordinates;
            map.setView([coords[1], coords[0]], 15);
        }
    } catch (err) {
        console.error(err);
    }
}

async function openJobDetail(issueId) {
    const modal = document.getElementById("jobDetailModal");
    const backdrop = document.getElementById("modalBackdrop");
    const body = document.getElementById("modalBody");
    const title = document.getElementById("modalTitle");
    const actionArea = document.getElementById("actionArea");
    
    body.innerHTML = `<div style="text-align: center; padding: 2rem;"><i class="fa-solid fa-spinner fa-spin"></i> Loading job details...</div>`;
    actionArea.innerHTML = "";
    
    backdrop.style.display = "block";
    modal.style.display = "flex";
    
    try {
        const res = await fetch(`/api/issues/${issueId}`);
        const data = await res.json();
        
        if (data.success) {
            const issue = data.data;
            title.innerText = issue.title;
            
            const beforeImg = issue.images.find(img => img.type === "before");
            
            body.innerHTML = `
                <div><strong>Description:</strong> ${issue.description}</div>
                <div><strong>Address:</strong> ${issue.address}</div>
                <div><strong>SLA Deadline:</strong> ${new Date(issue.sla_deadline).toLocaleString()}</div>
                <div><strong>Severity:</strong> <span class="badge ${issue.severity === 'critical' ? 'badge-critical' : 'badge-severity'}">${issue.severity}</span></div>
                
                ${beforeImg ? `
                    <div style="margin-top: 1rem;">
                        <strong>Citizen Evidence Photo:</strong>
                        <img src="${beforeImg.url}" style="width: 100%; border-radius: 8px; border: 1px solid var(--border-color); max-height: 200px; object-fit: cover; margin-top: 0.5rem;" />
                    </div>
                ` : ''}
            `;
            
            // Dynamic actions based on job status
            if (issue.status === "assigned") {
                actionArea.innerHTML = `
                    <button onclick="startJob('${issue._id}')" class="btn btn-primary" style="width: 100%; padding: 0.8rem;"><i class="fa-solid fa-play"></i> Start Work Order</button>
                `;
            } else if (issue.status === "work_started") {
                actionArea.innerHTML = `
                    <form id="resolveForm" onsubmit="submitResolution(event, '${issue._id}')">
                        <div class="form-group" style="margin-bottom: 1rem;">
                            <label class="form-label">Resolution Notes / Action Taken</label>
                            <textarea id="notes" class="form-control" rows="2" placeholder="Describe the repairs made, materials used, and details..." required></textarea>
                        </div>
                        <div class="form-group" style="margin-bottom: 1.5rem;">
                            <label class="form-label">Upload Repair Finish Photo</label>
                            <input type="file" id="afterImage" class="form-control" accept="image/*" required>
                        </div>
                        <button type="submit" class="btn btn-primary" style="width: 100%; padding: 0.8rem;"><i class="fa-solid fa-check-circle"></i> Submit Resolution</button>
                    </form>
                `;
            } else if (issue.status === "work_completed") {
                actionArea.innerHTML = `
                    <div style="text-align: center; color: var(--success); font-weight: 600; padding: 1rem; border: 1px dashed var(--success); border-radius: 8px;">
                        <i class="fa-solid fa-spinner fa-spin"></i> Awaiting Officer Verification
                    </div>
                `;
            }
        }
    } catch (err) {
        body.innerHTML = `<div style="text-align: center; color: var(--danger);">Failed to load task metadata.</div>`;
    }
}

function closeJobDetail() {
    document.getElementById("jobDetailModal").style.display = "none";
    document.getElementById("modalBackdrop").style.display = "none";
}

async function startJob(issueId) {
    try {
        const res = await fetch(`/api/issues/${issueId}/start`, { method: "POST" });
        const data = await res.json();
        if (data.success) {
            showToast("Work started on task order.", "success");
            closeJobDetail();
            loadMyJobs();
        } else {
            showToast(data.error.message || "Failed to start work.", "danger");
        }
    } catch (err) {
        showToast("Action failed.", "danger");
    }
}

async function submitResolution(e, issueId) {
    e.preventDefault();
    
    const formData = new FormData();
    formData.append("notes", document.getElementById("notes").value);
    
    const imgFile = document.getElementById("afterImage").files[0];
    if (imgFile) {
        formData.append("image", imgFile);
    }
    
    try {
        const res = await fetch(`/api/issues/${issueId}/resolve`, {
            method: "POST",
            body: formData
        });
        const data = await res.json();
        
        if (data.success) {
            showToast("Resolution submitted! AI status: " + data.data.status, "success");
            closeJobDetail();
            loadMyJobs();
        } else {
            showToast(data.error.message || "Action failed.", "danger");
        }
    } catch (err) {
        showToast("Server communication error.", "danger");
    }
}
