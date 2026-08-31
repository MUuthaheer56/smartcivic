/**
 * SmartCivic+ — Officer Dashboard JS
 */
let map;
let markerLayer = L.layerGroup();
let clusterLayer = L.layerGroup();
let heatmapLayer = L.layerGroup(); // simplified placeholder or custom logic
let workerLayer = L.layerGroup();

document.addEventListener("DOMContentLoaded", () => {
    switchTab("overview");
    loadOverviewStats();
    loadBriefing();
    loadEmergencyBar();
});

function switchTab(tabId) {
    // Reset active button class
    document.querySelectorAll(".sidebar-btn").forEach(btn => {
        btn.classList.remove("active");
        if (btn.getAttribute("onclick").includes(tabId)) {
            btn.classList.add("active");
        }
    });
    
    // Hide all tab panels
    document.getElementById("tab-overview").style.display = "none";
    document.getElementById("tab-issues-list").style.display = "none";
    document.getElementById("tab-map-view").style.display = "none";
    document.getElementById("tab-workers-view").style.display = "none";
    document.getElementById("tab-ward-health").style.display = "none";
    document.getElementById("tab-recurring").style.display = "none";
    
    if (tabId === "overview") {
        document.getElementById("tab-overview").style.display = "block";
        loadOverviewStats();
        loadBriefing();
    } else if (tabId === "map-view") {
        document.getElementById("tab-map-view").style.display = "block";
        setTimeout(initMap, 100);
    } else if (tabId === "workers-view") {
        document.getElementById("tab-workers-view").style.display = "block";
        loadWorkers();
    } else if (tabId === "ward-health") {
        document.getElementById("tab-ward-health").style.display = "block";
        loadWardHealth();
    } else if (tabId === "recurring") {
        document.getElementById("tab-recurring").style.display = "block";
        loadRecurringHotspots();
    } else {
        document.getElementById("tab-issues-list").style.display = "block";
        loadIssuesQueue(tabId);
        loadEmergencyBar(); // Check active emergencies
    }
}

async function loadOverviewStats() {
    try {
        const res = await fetch("/api/analytics/overview");
        const data = await res.json();
        if (data.success) {
            const stats = data.data;
            document.getElementById("statTotal").innerText = stats.total;
            document.getElementById("statResolved").innerText = stats.resolved;
            document.getElementById("statPending").innerText = stats.pending;
            document.getElementById("statCritical").innerText = stats.critical_active;
            
            // SLA Health Bar update
            const sla = stats.sla || {};
            document.getElementById("seg-ontrack").style.width = `${sla.on_track_pct || 0}%`;
            document.getElementById("seg-warning").style.width = `${sla.warning_pct || 0}%`;
            document.getElementById("seg-urgent").style.width = `${sla.urgent_pct || 0}%`;
            document.getElementById("seg-breached").style.width = `${sla.breached_pct || 0}%`;
            
            document.getElementById("lbl-ontrack").innerText = `${sla.on_track_pct || 0}%`;
            document.getElementById("lbl-warning").innerText = `${sla.warning_pct || 0}%`;
            document.getElementById("lbl-urgent").innerText = `${sla.urgent_pct || 0}%`;
            document.getElementById("lbl-breached").innerText = `${sla.breached_pct || 0}%`;
        }
    } catch (err) {
        console.error("Overview stats fetch failed: ", err);
    }
}

async function loadIssuesQueue(queueType) {
    const listTitle = document.getElementById("listTitle");
    const issuesGrid = document.getElementById("issuesGrid");
    issuesGrid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; padding: 2rem;"><i class="fa-solid fa-spinner fa-spin"></i> Loading issues...</div>`;
    
    let url = "/api/issues";
    if (queueType === "new-complaints") {
        listTitle.innerText = "New Complaints (Under Review)";
        url += "?status=ai_reviewed";
    } else if (queueType === "priority-queue") {
        listTitle.innerText = "Priority Queue";
        url += "?status=officer_reviewed";
    } else if (queueType === "in-progress") {
        listTitle.innerText = "In Progress Repairs";
        url += "?status=work_started";
    } else if (queueType === "verification") {
        listTitle.innerText = "Awaiting Verification";
        url += "?status=work_completed";
    } else if (queueType === "sla-alerts") {
        listTitle.innerText = "SLA Breach Warnings";
        url += "?severity=critical";
    }
    
    try {
        const res = await fetch(url);
        const data = await res.json();
        if (data.success) {
            issuesGrid.innerHTML = "";
            if (data.data.length === 0) {
                issuesGrid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: var(--text-muted); padding: 3rem;">No complaints in this queue.</div>`;
                return;
            }
            
            data.data.forEach(issue => {
                const ageHours = Math.round((new Date() - new Date(issue.created_at)) / 3600000);
                const hasDuplicate = issue.duplicate_of ? "Yes" : "No";
                
                const card = document.createElement("div");
                card.className = "glass-panel queue-card";
                card.innerHTML = `
                    <div class="queue-card-header">
                        <span class="badge ${issue.severity === 'critical' ? 'badge-critical' : 'badge-severity'}">${issue.severity}</span>
                        <span class="badge badge-status">${issue.status}</span>
                    </div>
                    <h4 style="font-family: var(--font-display); font-weight: 700; font-size: 1.05rem;">${issue.title}</h4>
                    <div style="font-size: 0.85rem; color: var(--text-muted);">${issue.description}</div>
                    <div style="font-size: 0.85rem; color: var(--text-muted); display: flex; flex-direction: column; gap: 0.25rem;">
                        <div><strong>Category:</strong> ${issue.category}</div>
                        <div><strong>Age:</strong> ${ageHours} hours old</div>
                        <div><strong>Priority Score:</strong> ${issue.priority_score}</div>
                        <div><strong>SLA Target:</strong> ${new Date(issue.sla_deadline).toLocaleTimeString()}</div>
                    </div>
                    
                    <div style="display: flex; gap: 0.5rem; margin-top: 0.75rem;">
                        ${issue.status === 'ai_reviewed' ? `
                            <button onclick="approveAIReview('${issue._id}')" class="btn btn-primary" style="flex: 1; padding: 0.5rem; font-size: 0.8rem;"><i class="fa-solid fa-check"></i> Approve</button>
                            <button onclick="overrideAIReview('${issue._id}')" class="btn btn-secondary" style="flex: 1; padding: 0.5rem; font-size: 0.8rem;"><i class="fa-solid fa-edit"></i> Override</button>
                        ` : ''}
                        
                        ${issue.status === 'officer_reviewed' ? `
                            <button onclick="openAssignWorker('${issue._id}')" class="btn btn-primary" style="width: 100%; padding: 0.5rem; font-size: 0.8rem;"><i class="fa-solid fa-user-plus"></i> Assign Worker</button>
                        ` : ''}
                        
                        ${issue.status === 'work_completed' ? `
                            <button onclick="verifyResolution('${issue._id}', true)" class="btn btn-primary" style="flex: 1; padding: 0.5rem; font-size: 0.8rem;"><i class="fa-solid fa-circle-check"></i> Approve</button>
                            <button onclick="verifyResolution('${issue._id}', false)" class="btn btn-secondary" style="flex: 1; padding: 0.5rem; font-size: 0.8rem; border-color: var(--danger); color: var(--danger);"><i class="fa-solid fa-rotate-left"></i> Reject</button>
                        ` : ''}
                    </div>
                `;
                issuesGrid.appendChild(card);
            });
        }
    } catch (err) {
        console.error("Queue fetch failed: ", err);
    }
}

async function approveAIReview(issueId) {
    try {
        const res = await fetch(`/api/issues/${issueId}/review`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ reason: "AI auto-classification confirmed by Officer." })
        });
        const data = await res.json();
        if (data.success) {
            showToast("Review approved and verified.", "success");
            loadIssuesQueue("new-complaints");
        }
    } catch (err) {
        showToast("Review action failed.", "danger");
    }
}

async function overrideAIReview(issueId) {
    const category = prompt("Override Category (road/water/electricity/sanitation/drainage/other):");
    const severity = prompt("Override Severity (low/medium/high/critical):");
    const department = prompt("Override Department (roads/water_supply/electrical/sanitation/drainage):");
    
    if (!category || !severity || !department) return;
    
    try {
        const res = await fetch(`/api/issues/${issueId}/review`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ category, severity, department, reason: "Manual override by Officer." })
        });
        const data = await res.json();
        if (data.success) {
            showToast("AI classification overridden successfully.", "success");
            loadIssuesQueue("new-complaints");
        }
    } catch (err) {
        showToast("Action failed.", "danger");
    }
}

async function openAssignWorker(issueId) {
    document.getElementById("assignIssueId").value = issueId;
    const recList = document.getElementById("recommendList");
    recList.innerHTML = `<div style="text-align: center; padding: 1.5rem;"><i class="fa-solid fa-spinner fa-spin"></i> Finding nearby matching crews...</div>`;
    
    document.getElementById("modalBackdrop").style.display = "block";
    document.getElementById("assignModal").style.display = "flex";
    
    try {
        const res = await fetch(`/api/workers/recommend?issue_id=${issueId}`);
        const data = await res.json();
        
        if (data.success) {
            recList.innerHTML = "";
            if (data.data.length === 0) {
                recList.innerHTML = `<div style="text-align: center; color: var(--text-muted); font-size: 0.9rem;">No available matching workers found in this area.</div>`;
                return;
            }
            
            data.data.forEach(rec => {
                const w = rec.worker;
                const recCard = document.createElement("div");
                recCard.className = "glass-panel";
                recCard.style.padding = "1rem";
                recCard.style.cursor = "pointer";
                recCard.style.display = "flex";
                recCard.style.justifyContent = "space-between";
                recCard.style.alignItems = "center";
                recCard.onclick = () => assignWorker(issueId, w.id);
                
                recCard.innerHTML = `
                    <div>
                        <strong style="font-size: 0.95rem;">${w.name}</strong>
                        <div style="font-size: 0.8rem; color: var(--text-muted);">Active Jobs: ${w.active_assignments} / ETA: ${rec.eta_minutes} mins</div>
                    </div>
                    <div style="text-align: right;">
                        <span class="badge" style="background: rgba(16, 185, 129, 0.2); color: var(--success); font-size: 0.8rem;">Match: ${rec.score}%</span>
                        <div style="font-size: 0.75rem; color: var(--text-muted); margin-top: 0.25rem;">Distance: ${rec.distance_km}km</div>
                    </div>
                `;
                recList.appendChild(recCard);
            });
        }
    } catch (err) {
        recList.innerHTML = `<div style="text-align: center; color: var(--danger);">Failed to load worker recommendations.</div>`;
    }
}

async function assignWorker(issueId, workerId) {
    try {
        const res = await fetch(`/api/issues/${issueId}/assign`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ worker_id: workerId })
        });
        const data = await res.json();
        if (data.success) {
            showToast("Worker assigned successfully!", "success");
            closeAssignModal();
            loadIssuesQueue("priority-queue");
        }
    } catch (err) {
        showToast("Assignment failed.", "danger");
    }
}

function closeAssignModal() {
    document.getElementById("modalBackdrop").style.display = "none";
    document.getElementById("assignModal").style.display = "none";
}

async function verifyResolution(issueId, approved) {
    const notes = prompt(approved ? "Resolution review feedback notes (optional):" : "Provide rejection reasons to field worker (required):");
    if (!approved && !notes) {
        showToast("Notes required to reject resolutions.", "warning");
        return;
    }
    
    try {
        const res = await fetch(`/api/issues/${issueId}/officer-verify`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ approved, notes: notes || "" })
        });
        const data = await res.json();
        if (data.success) {
            showToast(approved ? "Task resolution verified and forwarded." : "Resolution rejected and task sent back to worker.", "success");
            loadIssuesQueue("verification");
        }
    } catch (err) {
        showToast("Action failed.", "danger");
    }
}

function initMap() {
    if (map) return;
    
    map = L.map('officerMap').setView([12.9716, 77.5946], 13);
    
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap'
    }).addTo(map);
    
    markerLayer.addTo(map);
    clusterLayer.addTo(map);
    workerLayer.addTo(map);
    
    loadMapLayers();
    plotPredictiveHotspots();
}

async function loadMapLayers() {
    // 1. Load Issues Map markers
    try {
        const res = await fetch("/api/map/issues");
        const data = await res.json();
        if (data.success) {
            markerLayer.clearLayers();
            data.data.forEach(issue => {
                const coords = issue.location?.coordinates || [];
                if (coords.length === 2) {
                    const marker = L.marker([coords[1], coords[0]]);
                    
                    let langInfo = "";
                    if (issue.original_language && issue.original_language !== 'english') {
                        langInfo = `
                            <div style="margin-top: 0.5rem; padding: 0.5rem; background: rgba(255,255,255,0.05); border-radius: 4px; font-size: 0.8rem;">
                                <strong>Original (${issue.original_language}):</strong><br/>
                                <em>${issue.original_description || issue.description}</em>
                            </div>
                        `;
                    }
                    
                    const popupContent = `
                        <div style="font-family: 'Plus Jakarta Sans', sans-serif; min-width: 250px;">
                            <h4 style="margin: 0 0 5px 0; color: var(--text-main);">${issue.title}</h4>
                            <div style="font-size: 0.85rem; color: var(--text-muted); display:flex; flex-direction:column; gap:0.25rem;">
                                <div><strong>Status:</strong> <span class="badge badge-status">${issue.status}</span></div>
                                <div><strong>Severity:</strong> <span class="badge ${issue.severity === 'critical' ? 'badge-critical' : 'badge-severity'}">${issue.severity}</span></div>
                                <div><strong>Category:</strong> ${issue.category}</div>
                                <div><strong>Confirmations:</strong> ${issue.confirmation_count || 0}</div>
                                ${issue.is_recurring ? '<div><span class="badge badge-critical">⚠️ RECURRING HOTSPOT</span></div>' : ''}
                            </div>
                            ${langInfo}
                            <div style="margin-top: 0.75rem; border-top: 1px solid var(--border-color); padding-top: 0.5rem; display:flex; flex-direction:column; gap:0.5rem;">
                                <button onclick="openAssignWorker('${issue._id}')" class="btn btn-primary" style="padding: 0.3rem; font-size: 0.75rem;"><i class="fa-solid fa-user-plus"></i> Assign Worker</button>
                                <button onclick="showAuditInPopup('${issue._id}')" class="btn btn-secondary" style="padding: 0.3rem; font-size: 0.75rem;"><i class="fa-solid fa-clock-rotate-left"></i> View Audit Trail</button>
                            </div>
                            <div id="audit-popup-${issue._id}" style="margin-top: 0.5rem; max-height: 150px; overflow-y: auto; display: none;"></div>
                        </div>
                    `;
                    marker.bindPopup(popupContent);
                    markerLayer.addLayer(marker);
                }
            });
        }
    } catch (err) {
        console.error(err);
    }
    
    // 2. Load geo clusters
    try {
        const res = await fetch("/api/map/clusters");
        const data = await res.json();
        if (data.success) {
            clusterLayer.clearLayers();
            data.data.forEach(c => {
                const coords = c.location?.coordinates || [];
                if (coords.length === 2) {
                    const circle = L.circleMarker([coords[1], coords[0]], {
                        radius: Math.min(30, 8 + c.report_count * 2),
                        fillColor: "#ef4444",
                        color: "#ffffff",
                        weight: 2,
                        opacity: 0.8,
                        fillOpacity: 0.4
                    });
                    
                    circle.on('click', () => {
                        const sidebar = document.getElementById("mapSidebar");
                        sidebar.style.display = "flex";
                        sidebar.innerHTML = `
                            <h4 style="font-family: var(--font-display); font-weight: 700; border-bottom: 1px solid var(--border-color); padding-bottom: 0.5rem;">
                                Geohash Duplicate Cluster
                            </h4>
                            <div style="font-size: 0.9rem;">
                                <div><strong>Ward:</strong> ${c.ward}</div>
                                <div><strong>Reports Count:</strong> ${c.report_count}</div>
                                <div><strong>Category:</strong> ${c.category}</div>
                                <div><strong>Cluster Max Severity:</strong> ${c.severity}</div>
                            </div>
                            <button onclick="openAssignWorker('${c.issue_ids[0]}')" class="btn btn-primary" style="width: 100%; padding: 0.5rem; font-size: 0.8rem;">
                                <i class="fa-solid fa-user-plus"></i> Assign Worker
                            </button>
                            <button onclick="document.getElementById('mapSidebar').style.display='none'" class="btn btn-secondary" style="width: 100%; padding: 0.5rem; font-size: 0.8rem;">
                                Close
                            </button>
                        `;
                    });
                    clusterLayer.addLayer(circle);
                }
            });
        }
    } catch (err) {
        console.error(err);
    }
}

async function loadWorkers() {
    const workersGrid = document.getElementById("workersGrid");
    workersGrid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; padding: 2rem;"><i class="fa-solid fa-spinner fa-spin"></i> Loading crew status...</div>`;
    
    try {
        const res = await fetch("/api/workers");
        const data = await res.json();
        
        if (data.success) {
            workersGrid.innerHTML = "";
            data.data.forEach(w => {
                const card = document.createElement("div");
                card.className = "glass-panel queue-card";
                card.innerHTML = `
                    <div class="queue-card-header">
                        <span class="badge" style="background: rgba(59, 130, 246, 0.2); color: var(--primary)">${w.is_available ? 'Available' : 'Busy'}</span>
                        <strong style="color: var(--text-main);">${w.name}</strong>
                    </div>
                    <div style="font-size: 0.85rem; color: var(--text-muted); display: flex; flex-direction: column; gap: 0.25rem; margin-top: 0.5rem;">
                        <div><strong>Email:</strong> ${w.email}</div>
                        <div><strong>Ward:</strong> ${w.ward}</div>
                        <div><strong>Rating:</strong> ⭐ ${w.average_rating || 0.0} (${w.total_ratings || 0} ratings)</div>
                        <div><strong>Active Tasks:</strong> ${w.active_assignments} / 5 limit</div>
                        <div><strong>Skills:</strong> ${w.skills.join(', ') || 'General Repair'}</div>
                    </div>
                `;
                workersGrid.appendChild(card);
            });
        }
    } catch (err) {
        workersGrid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: var(--danger);">Failed to load worker profiles.</div>`;
    }
}

async function loadBriefing(forceRefresh = false) {
    try {
        const url = `/api/officer/briefing${forceRefresh ? '?refresh=true' : ''}`;
        const res = await fetch(url);
        const data = await res.json();
        if (data.success) {
            document.getElementById("briefingText").innerText = data.data.briefing_text;
            
            const actionsEl = document.getElementById("recommendedActions");
            actionsEl.innerHTML = "";
            if (data.data.recommended_actions.length === 0) {
                actionsEl.innerHTML = "<li>No urgent recommendation actions.</li>";
            } else {
                data.data.recommended_actions.forEach(act => {
                    const li = document.createElement("li");
                    li.innerText = act;
                    actionsEl.appendChild(li);
                });
            }
        }
    } catch (err) {
        console.error("Failed to load briefing", err);
    }
}

async function loadEmergencyBar() {
    try {
        const res = await fetch("/api/issues?severity=critical");
        const data = await res.json();
        const bar = document.getElementById("emergencyBar");
        const list = document.getElementById("emergencyList");
        
        if (data.success && data.data.length > 0) {
            list.innerHTML = "";
            data.data.forEach(issue => {
                if (issue.is_emergency) {
                    const row = document.createElement("div");
                    row.style = "display: flex; justify-content: space-between; align-items: center; background: rgba(255,255,255,0.05); padding: 0.8rem; border-radius: 6px;";
                    row.innerHTML = `
                        <div>
                            <strong>${issue.title} — ${issue.emergency_category || 'EMERGENCY'}</strong>
                            <div style="font-size: 0.8rem; color: var(--text-muted);">Ward ${issue.ward} · SLA: 1 hour</div>
                        </div>
                        <div style="display: flex; gap: 0.5rem;">
                            <button onclick="openAssignWorker('${issue._id}')" class="btn btn-primary" style="padding: 0.4rem 0.8rem; font-size: 0.75rem;"><i class="fa-solid fa-user-plus"></i> Assign Now</button>
                        </div>
                    `;
                    list.appendChild(row);
                }
            });
            
            if (list.children.length > 0) {
                bar.style.display = "block";
            } else {
                bar.style.display = "none";
            }
        } else {
            bar.style.display = "none";
        }
    } catch (err) {
        console.error("Emergency queue fetch failed", err);
    }
}

async function searchIssues() {
    const q = document.getElementById("searchQuery").value;
    const grid = document.getElementById("issuesGrid");
    grid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; padding: 2rem;"><i class="fa-solid fa-spinner fa-spin"></i> Querying NLP processor...</div>`;
    
    try {
        const res = await fetch(`/api/issues?q=${encodeURIComponent(q)}`);
        const data = await res.json();
        if (data.success) {
            grid.innerHTML = "";
            
            // Build tags below search
            const tagsEl = document.getElementById("searchTags");
            tagsEl.innerHTML = q.trim() !== "" ? `<span class="badge" style="background: rgba(56,189,248,0.2); color: var(--accent-primary);">NL Query: "${q}" <i class="fa-solid fa-times" onclick="clearSearch()" style="cursor:pointer; margin-left:5px;"></i></span>` : "";
            
            if (data.data.length === 0) {
                grid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: var(--text-muted); padding: 3rem;">No issues matching search criteria.</div>`;
                return;
            }
            
            data.data.forEach(issue => {
                const ageHours = Math.round((new Date() - new Date(issue.created_at)) / 3600000);
                const card = document.createElement("div");
                card.className = "glass-panel queue-card";
                card.innerHTML = `
                    <div class="queue-card-header">
                        <span class="badge ${issue.severity === 'critical' ? 'badge-critical' : 'badge-severity'}">${issue.severity}</span>
                        <span class="badge badge-status">${issue.status}</span>
                    </div>
                    <h4 style="font-family: var(--font-display); font-weight: 700; font-size: 1.05rem;">${issue.title}</h4>
                    <div style="font-size: 0.85rem; color: var(--text-muted);">${issue.description}</div>
                    <div style="font-size: 0.85rem; color: var(--text-muted); display: flex; flex-direction: column; gap: 0.25rem;">
                        <div><strong>Category:</strong> ${issue.category}</div>
                        <div><strong>Ward:</strong> ${issue.ward}</div>
                        <div><strong>Priority Score:</strong> ${issue.priority_score}</div>
                        <div><strong>Confirmations:</strong> ${issue.confirmation_count || 0} confirmations</div>
                    </div>
                    <div style="display: flex; gap: 0.5rem; margin-top: 0.75rem;">
                        <button onclick="openAssignWorker('${issue._id}')" class="btn btn-primary" style="width: 100%; padding: 0.5rem; font-size: 0.8rem;"><i class="fa-solid fa-user-plus"></i> Assign Worker</button>
                    </div>
                `;
                grid.appendChild(card);
            });
        }
    } catch (err) {
        grid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: var(--danger);">Search execution failed.</div>`;
    }
}

function clearSearch() {
    document.getElementById("searchQuery").value = "";
    document.getElementById("searchTags").innerHTML = "";
    loadIssuesQueue("new-complaints");
}

async function loadWardHealth() {
    const grid = document.getElementById("wardHealthGrid");
    grid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; padding: 2rem;"><i class="fa-solid fa-spinner fa-spin"></i> Calculating health ratios...</div>`;
    
    try {
        const res = await fetch("/api/analytics/by-ward");
        const data = await res.json();
        if (data.success) {
            grid.innerHTML = "";
            data.data.forEach(w => {
                const score = w.ward_health_score || 100;
                let barColor = '#10b981'; // Green
                if (score < 60) barColor = '#ef4444'; // Red
                else if (score < 80) barColor = '#f59e0b'; // Orange
                
                const card = document.createElement("div");
                card.className = "glass-panel queue-card";
                card.style = "padding: 1.5rem; display:flex; flex-direction:column; gap:0.5rem;";
                card.innerHTML = `
                    <h4 style="font-family: var(--font-display); font-weight:700;">${w.ward}</h4>
                    <div style="font-size: 0.85rem; color:var(--text-muted);">Active Complaints: <strong>${w.count}</strong></div>
                    <div style="margin-top: 0.5rem;">
                        <div style="display:flex; justify-content:space-between; font-size:0.85rem; margin-bottom: 0.25rem;">
                            <span>Health Score</span>
                            <span style="color: ${barColor}; font-weight:700;">${score}/100</span>
                        </div>
                        <div style="width:100%; height:10px; background:rgba(255,255,255,0.05); border-radius:5px; overflow:hidden;">
                            <div style="width:${score}%; height:100%; background:${barColor};"></div>
                        </div>
                    </div>
                `;
                grid.appendChild(card);
            });
        }
    } catch (err) {
        grid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: var(--danger);">Failed to load health statistics.</div>`;
    }
}

async function loadRecurringHotspots() {
    const grid = document.getElementById("recurringGrid");
    grid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; padding: 2rem;"><i class="fa-solid fa-spinner fa-spin"></i> Scanning hotspots...</div>`;
    
    try {
        const res = await fetch("/api/analytics/recurring");
        const data = await res.json();
        if (data.success) {
            grid.innerHTML = "";
            if (data.data.length === 0) {
                grid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: var(--text-muted); padding: 3rem;">No recurring hotspots detected yet.</div>`;
                return;
            }
            data.data.forEach(h => {
                const card = document.createElement("div");
                card.className = "glass-panel queue-card";
                card.innerHTML = `
                    <div class="queue-card-header">
                        <span class="badge badge-critical"><i class="fa-solid fa-arrows-spin"></i> RECURRING</span>
                        <strong style="color:var(--text-main);">${h.category.toUpperCase()}</strong>
                    </div>
                    <div style="font-size: 0.85rem; color: var(--text-muted); display: flex; flex-direction: column; gap: 0.25rem; margin-top: 0.5rem;">
                        <div><strong>Ward:</strong> ${h.ward}</div>
                        <div><strong>Total Occurrences:</strong> ${h.total_occurrences} times</div>
                        <div><strong>First Reported:</strong> ${new Date(h.first_occurrence).toLocaleDateString()}</div>
                        <div><strong>Latest:</strong> ${new Date(h.last_occurrence).toLocaleDateString()}</div>
                    </div>
                `;
                grid.appendChild(card);
            });
        }
    } catch (err) {
        grid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: var(--danger);">Failed to load recurring hotspots.</div>`;
    }
}

async function loadAuditTrail(issueId) {
    const auditEl = document.getElementById("auditTrailList");
    if (!auditEl) return;
    auditEl.innerHTML = `<div style="text-align: center; padding: 1rem;"><i class="fa-solid fa-spinner fa-spin"></i> Loading audit trail...</div>`;
    
    try {
        const res = await fetch(`/api/issues/${issueId}/audit-log`);
        const data = await res.json();
        if (data.success) {
            auditEl.innerHTML = "";
            data.data.forEach(log => {
                const li = document.createElement("div");
                li.style = "font-size: 0.85rem; display: flex; flex-direction:column; border-bottom: 1px solid rgba(255,255,255,0.05); padding: 0.5rem 0;";
                li.innerHTML = `
                    <div style="display:flex; justify-content:space-between; font-weight:600; color: var(--text-main);">
                        <span>${log.actor_name} (${log.action})</span>
                        <span style="font-size:0.75rem; color: var(--text-muted);">${new Date(log.timestamp).toLocaleString()}</span>
                    </div>
                    <div style="color: var(--text-muted); margin-top: 0.25rem;">
                        ${log.reason || 'State alteration recorded.'}
                        ${log.field_changed ? `<br/><span style="font-size: 0.8rem; color: var(--accent-primary);">Changed: ${log.field_changed} (${log.old_value} → ${log.new_value})</span>` : ''}
                    </div>
                `;
                auditEl.appendChild(li);
            });
        }
    } catch (err) {
        auditEl.innerHTML = `<div style="color: var(--danger);">Failed to load audit logs.</div>`;
    }
}

// Hook map init to load predictive hotspots
let hotspotCircles = [];
async function plotPredictiveHotspots() {
    try {
        const res = await fetch("/api/map/hotspots");
        const data = await res.json();
        if (data.success) {
            hotspotCircles.forEach(c => map.removeLayer(c));
            hotspotCircles = [];
            
            data.data.forEach(h => {
                const lat = h.lat;
                const lng = h.lng;
                const risk = h.hotspot_risk;
                const category = h.category;
                
                let color = '#fb7185'; // pink/red
                if (risk === 'medium') color = '#fbbf24'; // orange
                else if (risk === 'low') color = '#34d399'; // green
                
                const circle = L.circle([lat, lng], {
                    radius: 500, // 500m radius
                    color: color,
                    fillColor: color,
                    fillOpacity: 0.2
                }).addTo(map);
                
                circle.bindPopup(`
                    <div style="font-family: 'Plus Jakarta Sans', sans-serif;">
                        <h4 style="margin:0 0 5px 0; color: #e11d48;"><i class="fa-solid fa-triangle-exclamation"></i> Predicted Hotspot</h4>
                        <p style="margin:0; font-size:0.8rem; color:#475569;">Category: <strong>${category.toUpperCase()}</strong></p>
                        <p style="margin:0; font-size:0.8rem; color:#475569;">Risk Level: <strong>${risk.toUpperCase()}</strong></p>
                        <p style="margin:0; font-size:0.8rem; color:#475569;">Recurrence Rate: <strong>${h.recurrence_rate}/month</strong></p>
                    </div>
                `);
                hotspotCircles.push(circle);
            });
        }
    } catch (err) {
        console.error("Failed to plot hotspots", err);
    }
}

async function showAuditInPopup(issueId) {
    const container = document.getElementById(`audit-popup-${issueId}`);
    if (!container) return;
    
    if (container.style.display === "block") {
        container.style.display = "none";
        return;
    }
    
    container.style.display = "block";
    container.innerHTML = `<div style="font-size:0.75rem; text-align:center; color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin"></i> Loading...</div>`;
    
    try {
        const res = await fetch(`/api/issues/${issueId}/audit-log`);
        const data = await res.json();
        if (data.success) {
            container.innerHTML = "";
            if (data.data.length === 0) {
                container.innerHTML = `<div style="font-size:0.75rem; text-align:center; color:var(--text-muted);">No log records yet.</div>`;
                return;
            }
            
            data.data.forEach(log => {
                const item = document.createElement("div");
                item.style = "font-size:0.75rem; border-bottom:1px solid rgba(255,255,255,0.05); padding: 0.25rem 0;";
                item.innerHTML = `
                    <div style="display:flex; justify-content:space-between; font-weight:600; color:var(--text-main);">
                        <span>${log.action}</span>
                        <span style="font-size:0.7rem; color:var(--text-muted);">${new Date(log.timestamp).toLocaleTimeString()}</span>
                    </div>
                    <div style="color:var(--text-muted); font-size:0.7rem;">
                        By: ${log.actor_name}<br/>
                        ${log.reason || ''}
                    </div>
                `;
                container.appendChild(item);
            });
        } else {
            container.innerHTML = `<div style="font-size:0.75rem; color:var(--danger);">Error loading logs.</div>`;
        }
    } catch (err) {
        container.innerHTML = `<div style="font-size:0.75rem; color:var(--danger);">Network error.</div>`;
    }
}
