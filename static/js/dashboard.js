/**
 * SmartCivic+ — Officer Dashboard JS
 */
let map;
let markerLayer = L.layerGroup();
let clusterLayer = L.layerGroup();
let heatmapLayer = L.layerGroup(); // simplified placeholder or custom logic
let workerLayer = L.layerGroup();

let officerFilter;
let allOfficerQueueIssues = [];

// In-memory tab caching to prevent request bursts (UI-REPAIR requirement 6)
const _dashboardCache = {};
const DASHBOARD_CACHE_TTL_MS = 60000; // 60s cache

function getCached(key) {
    const entry = _dashboardCache[key];
    if (entry && (Date.now() - entry.time < DASHBOARD_CACHE_TTL_MS)) {
        return entry.data;
    }
    return null;
}

function setCached(key, data) {
    _dashboardCache[key] = { data, time: Date.now() };
}

document.addEventListener("DOMContentLoaded", () => {
    officerFilter = new SmartCivicFilter({
        containerId: 'filterBar',
        onFilterChange: () => renderOfficerIssuesQueue()
    });
    // Load only the initial active tab (overview) - no parallel burst
    switchTab("overview");
});

let currentApprovalRole = "citizen";

function setActiveQueueGrid(activeGridId) {
    const issuesGrid = document.getElementById("issuesGrid");
    const verificationGrid = document.getElementById("verificationGrid");
    if (issuesGrid) {
        issuesGrid.style.display = activeGridId === "issuesGrid" ? "grid" : "none";
    }
    if (verificationGrid) {
        verificationGrid.style.display = activeGridId === "verificationGrid" ? "grid" : "none";
    }
}

function switchTab(tabId) {
    // Reset active button class
    document.querySelectorAll(".sidebar-btn").forEach(btn => {
        btn.classList.remove("active");
        if (btn.getAttribute("onclick") && btn.getAttribute("onclick").includes(tabId)) {
            btn.classList.add("active");
        }
    });

    // Hide all tab panels
    const tabPanels = ["tab-overview", "tab-issues-list", "tab-account-approvals", "tab-map-view", "tab-workers-view", "tab-ward-health", "tab-recurring", "tab-simulation", "tab-announcements"];
    tabPanels.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.style.display = "none";
    });

    if (tabId === "overview") {
        const el = document.getElementById("tab-overview");
        if (el) el.style.display = "block";
        loadOverviewStats();
        loadBriefing();
        loadEmergencyBar();
    } else if (tabId === "account-approvals") {
        const el = document.getElementById("tab-account-approvals");
        if (el) el.style.display = "block";
        loadPendingAccountApprovals(currentApprovalRole);
    } else if (tabId === "map-view") {
        const el = document.getElementById("tab-map-view");
        if (el) el.style.display = "block";
        setTimeout(() => {
            initMap();
            if (map) map.invalidateSize();
        }, 100);
    } else if (tabId === "workers-view") {
        const el = document.getElementById("tab-workers-view");
        if (el) el.style.display = "block";
        loadWorkers();
    } else if (tabId === "ward-health") {
        const el = document.getElementById("tab-ward-health");
        if (el) el.style.display = "block";
        loadWardHealth();
    } else if (tabId === "recurring") {
        const el = document.getElementById("tab-recurring");
        if (el) el.style.display = "block";
        loadRecurringHotspots();
    } else if (tabId === "simulation") {
        const el = document.getElementById("tab-simulation");
        if (el) el.style.display = "block";
    } else if (tabId === "announcements") {
        const el = document.getElementById("tab-announcements");
        if (el) el.style.display = "block";
        loadAdminAnnouncements();
    } else {
        const el = document.getElementById("tab-issues-list");
        if (el) el.style.display = "block";
        setActiveQueueGrid(tabId === "verification" ? "verificationGrid" : "issuesGrid");
        loadIssuesQueue(tabId);
        loadEmergencyBar();
    }
}

function switchApprovalTab(role) {
    currentApprovalRole = role;
    const btnRes = document.getElementById("btn-approvals-residents");
    const btnWork = document.getElementById("btn-approvals-workers");
    if (btnRes && btnWork) {
        if (role === 'citizen') {
            btnRes.classList.add("active");
            btnRes.style.background = "var(--primary)";
            btnRes.style.color = "#fff";
            btnWork.classList.remove("active");
            btnWork.style.background = "transparent";
            btnWork.style.color = "var(--text-muted)";
        } else {
            btnWork.classList.add("active");
            btnWork.style.background = "var(--primary)";
            btnWork.style.color = "#fff";
            btnRes.classList.remove("active");
            btnRes.style.background = "transparent";
            btnRes.style.color = "var(--text-muted)";
        }
    }
    loadPendingAccountApprovals(role);
}

function renderOverviewStats(stats) {
    if (!stats) return;
    const elTotal = document.getElementById("statTotal");
    if (elTotal) elTotal.innerText = stats.total ?? 0;
    const elResolved = document.getElementById("statResolved");
    if (elResolved) elResolved.innerText = stats.resolved ?? 0;
    const elPending = document.getElementById("statPending");
    if (elPending) elPending.innerText = stats.pending ?? 0;
    const elCritical = document.getElementById("statCritical");
    if (elCritical) elCritical.innerText = stats.critical_active ?? 0;

    const sla = stats.sla || {};
    const setW = (id, val) => { const el = document.getElementById(id); if (el) el.style.width = `${val || 0}%`; };
    const setT = (id, val) => { const el = document.getElementById(id); if (el) el.innerText = `${val || 0}%`; };
    setW("seg-ontrack", sla.on_track_pct);
    setW("seg-warning", sla.warning_pct);
    setW("seg-urgent", sla.urgent_pct);
    setW("seg-breached", sla.breached_pct);

    setT("lbl-ontrack", sla.on_track_pct);
    setT("lbl-warning", sla.warning_pct);
    setT("lbl-urgent", sla.urgent_pct);
    setT("lbl-breached", sla.breached_pct);
}

async function loadOverviewStats(force = false) {
    if (!force) {
        const cached = getCached('overview_stats');
        if (cached) {
            renderOverviewStats(cached);
            return;
        }
    }
    try {
        const fetchFn = window.api || window.fetch;
        const res = await fetchFn("/api/analytics/overview");
        const data = (res && typeof res.json === "function" && !(res instanceof Response)) ? res : (res.data ? res : await res.json());
        if (data && data.success) {
            setCached('overview_stats', data.data);
            renderOverviewStats(data.data);
        }
    } catch (err) {
        console.error("Overview stats fetch failed:", err);
    }
}

async function loadIssuesQueue(queueType, force = false) {
    const listTitle = document.getElementById("listTitle");
    const activeGridId = queueType === "verification" ? "verificationGrid" : "issuesGrid";
    const issuesGrid = document.getElementById(activeGridId);
    if (!issuesGrid) return;
    setActiveQueueGrid(activeGridId);

    if (queueType === "verification") {
        if (listTitle) listTitle.innerText = "Pending Resident & Worker Verification";
        renderPendingResidentVerifications();
        return;
    }

    let url = "/api/issues";
    if (queueType === "new-complaints") {
        if (listTitle) listTitle.innerText = "New Complaints (Under Review)";
        url += "?status=submitted,ai_reviewed";
    } else if (queueType === "priority-queue") {
        if (listTitle) listTitle.innerText = "Priority Queue";
        url += "?status=submitted,ai_reviewed,officer_reviewed&sort=priority_score";
    } else if (queueType === "in-progress") {
        if (listTitle) listTitle.innerText = "In Progress Repairs";
        url += "?status=work_started";
    } else if (queueType === "sla-alerts") {
        if (listTitle) listTitle.innerText = "SLA Breach Warnings";
        url += "?severity=critical";
    }

    if (!force) {
        const cached = getCached('queue_' + queueType);
        if (cached) {
            allOfficerQueueIssues = cached;
            renderOfficerIssuesQueue();
            return;
        }
    }

    if (typeof window.renderLoading === "function") {
        window.renderLoading(issuesGrid, "Loading issues...");
    } else {
        issuesGrid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; padding: 2rem;"><i class="fa-solid fa-spinner fa-spin"></i> Loading issues...</div>`;
    }

    try {
        const fetchFn = window.api || window.fetch;
        const res = await fetchFn(url);
        const data = (res && typeof res.json === "function" && !(res instanceof Response)) ? res : (res.data ? res : await res.json());
        if (data && data.success) {
            allOfficerQueueIssues = data.data || [];
            setCached('queue_' + queueType, allOfficerQueueIssues);
            renderOfficerIssuesQueue();
        } else {
            if (typeof window.renderErrorRetry === "function") {
                window.renderErrorRetry(issuesGrid, "Failed to load issues.", () => loadIssuesQueue(queueType, true));
            } else {
                issuesGrid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: var(--danger);">Failed to load issues.</div>`;
            }
        }
    } catch (err) {
        console.error("Queue fetch failed: ", err);
        if (typeof window.renderErrorRetry === "function") {
            window.renderErrorRetry(issuesGrid, "Failed to load issues. Check connection.", () => loadIssuesQueue(queueType, true));
        } else {
            issuesGrid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: var(--danger);">Failed to load issues.</div>`;
        }
    }
}

async function renderPendingResidentVerifications() {
    const verificationGrid = document.getElementById("verificationGrid");
    const issuesGrid = document.getElementById("issuesGrid");
    if (verificationGrid) {
        verificationGrid.style.display = "grid";
    }
    if (issuesGrid && verificationGrid) {
        issuesGrid.style.display = "none";
    }
    loadPendingAccountApprovals("citizen");
}

function renderApprovalsList(users, role) {
    const approvalsGrid = document.getElementById("approvalsGrid") || (document.getElementById("verificationGrid") && document.getElementById("tab-issues-list") && document.getElementById("tab-issues-list").style.display !== "none" ? document.getElementById("verificationGrid") : document.getElementById("issuesGrid"));
    if (!approvalsGrid) return;
    if (users.length === 0) {
        approvalsGrid.innerHTML = `<div class="empty-state" style="grid-column: 1/-1;"><i class="fa-solid fa-user-check empty-state-icon"></i><div>No ${role === 'worker' ? 'workers' : 'residents'} are pending approval.</div></div>`;
        return;
    }

    approvalsGrid.innerHTML = "";
    const esc = window.escapeHtml || (s => s ? String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#039;') : '');
    users.forEach(user => {
        const card = document.createElement("div");
        card.className = "glass-panel queue-card";
        const registeredDate = user.created_at ? new Date(user.created_at).toLocaleDateString() : 'N/A';
        const safeId = encodeURIComponent(String(user._id || ''));
        card.innerHTML = `
            <div class="queue-card-header">
                <span class="badge badge-status">${esc((user.verification_status || user.status || 'pending').toUpperCase())}</span>
                <span class="badge ${user.verified ? 'badge-low' : 'badge-warning'}">${user.verified ? 'Verified' : 'Pending'}</span>
            </div>
            <h4 style="font-family: var(--font-display); font-weight: 700; font-size: 1.05rem; color: #ffffff;">${esc(user.name || (user.role === 'worker' ? 'Worker Crew' : 'Resident'))}</h4>
            <div style="font-size: 0.85rem; color: var(--text-muted); display: flex; flex-direction: column; gap: 0.35rem;">
                <div><strong>Role:</strong> <span style="color: var(--text-main);">${esc(user.role || 'resident')}</span></div>
                <div><strong>Email:</strong> <span style="color: var(--text-main);">${esc(user.email || 'Unknown')}</span></div>
                <div><strong>Ward:</strong> <span style="color: var(--text-main);">${esc(user.ward || 'Ward 1')}</span></div>
                <div><strong>Registered On:</strong> <span style="color: var(--text-main);">${esc(registeredDate)}</span></div>
                <div><strong>Status:</strong> <span style="color: var(--warning);">${esc(user.status || 'pending_verification')}</span></div>
            </div>
            <div style="display: flex; gap: 0.5rem; margin-top: 0.75rem;">
                <button onclick="approveResidentVerification('${safeId}')" class="btn btn-primary" style="flex: 1; padding: 0.5rem; font-size: 0.8rem;"><i class="fa-solid fa-check"></i> Approve</button>
                <button onclick="rejectResidentVerification('${safeId}')" class="btn btn-secondary" style="flex: 1; padding: 0.5rem; font-size: 0.8rem; border-color: var(--danger); color: var(--danger);"><i class="fa-solid fa-ban"></i> Reject</button>
            </div>
        `;
        approvalsGrid.appendChild(card);
    });
}

async function loadPendingAccountApprovals(role = "citizen", force = false) {
    const tabIssuesList = document.getElementById("tab-issues-list");
    const approvalsGrid = document.getElementById("approvalsGrid") ||
        ((tabIssuesList && tabIssuesList.style.display !== "none") ? document.getElementById("verificationGrid") || document.getElementById("issuesGrid") : document.getElementById("issuesGrid"));
    if (!approvalsGrid) return;

    if (!force) {
        const cached = getCached('approvals_' + role);
        if (cached) {
            renderApprovalsList(cached, role);
            return;
        }
    }

    if (typeof window.renderLoading === "function") {
        window.renderLoading(approvalsGrid, `Loading pending ${role === 'worker' ? 'worker' : 'resident'} approvals...`);
    } else {
        approvalsGrid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; padding: 2rem;"><i class="fa-solid fa-spinner fa-spin"></i> Loading pending ${role === 'worker' ? 'worker' : 'resident'} approvals...</div>`;
    }

    try {
        const fetchFn = window.api || window.fetch;
        const res = await fetchFn(`/api/auth/users/pending?role=${role}`);
        const data = (res && typeof res.json === "function" && !(res instanceof Response)) ? res : (res.data ? res : await res.json());
        if (!data || !data.success) {
            if (typeof window.renderErrorRetry === "function") {
                window.renderErrorRetry(approvalsGrid, "Unable to load approval queue.", () => loadPendingAccountApprovals(role, true));
            } else {
                approvalsGrid.innerHTML = '<div class="empty-state" style="grid-column: 1/-1;"><div>Unable to load approval queue.</div></div>';
            }
            return;
        }

        const users = data.data || [];
        setCached('approvals_' + role, users);
        renderApprovalsList(users, role);
    } catch (err) {
        console.error("Pending account approval load failed:", err);
        if (typeof window.renderErrorRetry === "function") {
            window.renderErrorRetry(approvalsGrid, "Failed to load pending approvals.", () => loadPendingAccountApprovals(role, true));
        } else {
            approvalsGrid.innerHTML = '<div class="empty-state" style="grid-column: 1/-1;"><div>Failed to load pending approvals.</div></div>';
        }
    }
}

async function approveResidentVerification(userId) {
    try {
        const res = await fetch(`/api/auth/users/${userId}/verify`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'approve', ward_id: 'ward_1' })
        });
        const data = await res.json();
        if (data.success) {
            showToast('Account approved successfully.', 'success');
            loadPendingAccountApprovals(currentApprovalRole);
        } else {
            showToast(data.error?.message || 'Approval failed.', 'danger');
        }
    } catch (err) {
        console.error(err);
        showToast('Approval request failed.', 'danger');
    }
}

async function rejectResidentVerification(userId) {
    const reason = prompt("Enter reason for rejecting this user registration:", "Invalid proof of residence");
    if (reason === null) return; // cancelled

    try {
        const res = await fetch(`/api/auth/users/${userId}/verify`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'reject', reason: reason })
        });
        const data = await res.json();
        if (data.success) {
            showToast('User registration rejected.', 'success');
            loadPendingAccountApprovals(currentApprovalRole);
        } else {
            showToast(data.error?.message || 'Rejection failed.', 'danger');
        }
    } catch (err) {
        console.error(err);
        showToast('Rejection request failed.', 'danger');
    }
}

function renderOfficerIssuesQueue() {
    const issuesGrid = document.getElementById("issuesGrid");
    if (!issuesGrid) return;
    issuesGrid.innerHTML = "";

    const filtered = allOfficerQueueIssues.filter(item => officerFilter ? officerFilter.filterItem(item) : true);
    if (officerFilter) officerFilter.updateBadge(filtered.length, allOfficerQueueIssues.length);

    if (filtered.length === 0) {
        issuesGrid.innerHTML = `
            <div class="empty-state" style="grid-column: 1/-1;">
                <i class="fa-solid fa-inbox empty-state-icon"></i>
                <div>No complaints match the selected filters.</div>
            </div>`;
        return;
    }

    filtered.forEach(issue => {
        const ageHours = Math.round((new Date() - new Date(issue.created_at)) / 3600000);
        const sev = (issue.severity || 'medium').toLowerCase();
        let badgeClass = 'badge-medium';
        if (sev === 'critical') badgeClass = 'badge-critical';
        else if (sev === 'high') badgeClass = 'badge-high';
        else if (sev === 'low') badgeClass = 'badge-low';

        const esc = window.escapeHtml || (s => s ? String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#039;') : '');
        const imgObj = issue.image;
        const imgUrl = (imgObj && typeof imgObj === 'object' ? imgObj.url : (typeof imgObj === 'string' ? imgObj : null))
            || (issue.images && issue.images[0] ? (issue.images[0].url || issue.images[0]) : null)
            || (issue.thumbnail_url && !issue.thumbnail_url.includes('placeholder') ? issue.thumbnail_url : null);
        const imgDets = issue.image_detections || (issue.ai_analysis && issue.ai_analysis.image_detections) || [];
        const visDefect = issue.visual_evidence?.defect_name;
        const defectName = imgDets.length > 0 ? imgDets.join(', ') : (visDefect || (issue.category === 'road' && issue.type ? issue.type : null));
        const hasAiDetection = !!defectName && (imgDets.length > 0 || !!visDefect || issue.ai_analysis?.image_analysis_available);

        const card = document.createElement("div");
        card.className = "glass-panel queue-card";
        const safeIssueId = encodeURIComponent(String(issue._id || ''));
        card.innerHTML = `
            <div class="queue-card-header">
                <span class="badge ${badgeClass}">${esc(issue.severity)}</span>
                <span class="badge badge-status">${esc(issue.status)}</span>
            </div>
            <h4 style="font-family: var(--font-display); font-weight: 700; font-size: 1.05rem; color: #ffffff;">${esc(issue.title)}</h4>
            <div style="font-size: 0.85rem; color: var(--sc-muted);">${esc(issue.description)}</div>
            
            ${imgUrl ? `
                <div style="position: relative; border-radius: 8px; overflow: hidden; margin: 0.35rem 0;">
                    <img src="${esc(imgUrl)}" alt="Citizen Evidence Photo" class="queue-photo-preview" loading="lazy" />
                    ${hasAiDetection ? `
                    <div style="position: absolute; bottom: 0; left: 0; right: 0; padding: 0.35rem 0.65rem; background: rgba(11,20,55,0.88); color: #6ee7b7; font-size: 0.76rem; font-weight: 700; display: flex; align-items: center; gap: 0.35rem;">
                        <i class="fa-solid fa-robot"></i> AI Detected in Photo: <strong>${esc(defectName)}</strong>
                    </div>
                    ` : ''}
                </div>
            ` : ''}

            <div style="font-size: 0.85rem; color: var(--sc-muted); display: flex; flex-direction: column; gap: 0.25rem;">
                <div><strong>Category:</strong> ${esc(issue.category)}</div>
                <div><strong>Issue Type:</strong> ${esc(issue.type || 'other')}</div>
                ${hasAiDetection ? `
                    <div class="queue-card-ai-vision detected">
                        <i class="fa-solid fa-microchip"></i>
                        <span>AI Detected in Image: <strong>${esc(defectName)}</strong></span>
                    </div>
                ` : `
                    <div><strong>AI Vision:</strong> ${issue.ai_analysis?.image_analysis_available ? 'Analyzed' : 'No defect detected / No photo'}</div>
                `}
                <div><strong>AI Explanation:</strong> ${esc(issue.ai_analysis?.explanation || 'Not available')}</div>
                <div><strong>Age:</strong> ${Number(ageHours || 0)} hours old</div>
                <div><strong>Priority Score:</strong> ${Number(issue.priority_score || 0)}</div>
                <div><strong>SLA Target:</strong> ${new Date(issue.sla_deadline || Date.now()).toLocaleTimeString()}</div>
            </div>
            
            <div style="display: flex; gap: 0.5rem; margin-top: 0.75rem;">
                ${['submitted', 'ai_reviewed'].includes(issue.status) ? `
                    <button onclick="approveAIReview('${safeIssueId}')" class="btn btn-primary" style="flex: 1; padding: 0.5rem; font-size: 0.8rem;"><i class="fa-solid fa-check"></i> Approve</button>
                    <button onclick="overrideAIReview('${safeIssueId}')" class="btn btn-secondary" style="flex: 1; padding: 0.5rem; font-size: 0.8rem;"><i class="fa-solid fa-edit"></i> Override</button>
                    <button onclick="rejectIssue('${safeIssueId}')" class="btn btn-secondary" style="flex: 1; padding: 0.5rem; font-size: 0.8rem; border-color: var(--danger); color: var(--danger);"><i class="fa-solid fa-ban"></i> Reject</button>
                ` : ''}
                
                ${issue.status === 'officer_reviewed' ? `
                    <button onclick="openAssignWorker('${safeIssueId}')" class="btn btn-primary" style="flex: 1; padding: 0.5rem; font-size: 0.8rem;"><i class="fa-solid fa-user-plus"></i> Assign Worker</button>
                    <button onclick="rejectIssue('${safeIssueId}')" class="btn btn-secondary" style="flex: 1; padding: 0.5rem; font-size: 0.8rem; border-color: var(--danger); color: var(--danger);"><i class="fa-solid fa-ban"></i> Reject</button>
                ` : ''}
                
                ${issue.status === 'work_completed' ? `
                    <button onclick="verifyResolution('${safeIssueId}', true)" class="btn btn-primary" style="flex: 1; padding: 0.5rem; font-size: 0.8rem;"><i class="fa-solid fa-circle-check"></i> Approve</button>
                    <button onclick="verifyResolution('${safeIssueId}', false)" class="btn btn-secondary" style="flex: 1; padding: 0.5rem; font-size: 0.8rem; border-color: var(--sc-critical-border); color: var(--sc-critical-text);"><i class="fa-solid fa-rotate-left"></i> Reject</button>
                ` : ''}
            </div>
        `;
        issuesGrid.appendChild(card);
    });
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
    const type = prompt("Override Issue Type (optional):");

    if (!category || !severity || !department) return;

    try {
        const res = await fetch(`/api/issues/${issueId}/review`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ category, severity, department, type, reason: "Manual override by Officer." })
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

async function rejectIssue(issueId) {
    const reason = prompt("Reason for rejection (required):");
    if (!reason || !reason.trim()) return;
    try {
        const res = await fetch(`/api/issues/${issueId}/reject`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ reason })
        });
        const data = await res.json();
        if (data.success) {
            showToast("Issue rejected successfully", "success");
            loadIssuesQueue("new-complaints");
        } else {
            showToast(data.error?.message || "Reject failed", "danger");
        }
    } catch (err) {
        showToast("Server error during reject action.", "danger");
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

        if (!res.ok || !data.success) {
            const errorMessage = document.createElement("div");
            errorMessage.style.textAlign = "center";
            errorMessage.style.color = "var(--danger)";
            errorMessage.textContent = data.error?.message || "Unable to load worker recommendations.";
            recList.replaceChildren(errorMessage);
            return;
        }

        recList.innerHTML = "";
        if (!Array.isArray(data.data) || data.data.length === 0) {
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
        if (!res.ok || !data.success) {
            showToast(data.error?.message || "Assignment failed.", "danger");
            return;
        }

        showToast("Worker assigned successfully!", "success");
        closeAssignModal();
        loadIssuesQueue("priority-queue");
    } catch (err) {
        console.error("Worker assignment failed:", err);
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

                    const esc = window.escapeHtml || (s => s ? String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#039;') : '');
                    const safeIssueId = encodeURIComponent(String(issue._id || ''));
                    let langInfo = "";
                    if (issue.original_language && issue.original_language !== 'english') {
                        langInfo = `
                            <div style="margin-top: 0.5rem; padding: 0.5rem; background: rgba(255,255,255,0.05); border-radius: 4px; font-size: 0.8rem;">
                                <strong>Original (${esc(issue.original_language)}):</strong><br/>
                                <em>${esc(issue.original_description || issue.description)}</em>
                            </div>
                        `;
                    }

                    const popupContent = `
                        <div style="font-family: 'Plus Jakarta Sans', sans-serif; min-width: 250px;">
                            <h4 style="margin: 0 0 5px 0; color: var(--text-main);">${esc(issue.title)}</h4>
                            <div style="font-size: 0.85rem; color: var(--text-muted); display:flex; flex-direction:column; gap:0.25rem;">
                                <div><strong>Status:</strong> <span class="badge badge-status">${esc(issue.status)}</span></div>
                                <div><strong>Severity:</strong> <span class="badge ${issue.severity === 'critical' ? 'badge-critical' : 'badge-severity'}">${esc(issue.severity)}</span></div>
                                <div><strong>Category:</strong> ${esc(issue.category)}</div>
                                <div><strong>Confirmations:</strong> ${Number(issue.confirmation_count || 0)}</div>
                                ${issue.is_recurring ? '<div><span class="badge badge-critical">⚠️ RECURRING HOTSPOT</span></div>' : ''}
                            </div>
                            ${langInfo}
                            <div style="margin-top: 0.75rem; border-top: 1px solid var(--border-color); padding-top: 0.5rem; display:flex; flex-direction:column; gap:0.5rem;">
                                <button onclick="openAssignWorker('${safeIssueId}')" class="btn btn-primary" style="padding: 0.3rem; font-size: 0.75rem;"><i class="fa-solid fa-user-plus"></i> Assign Worker</button>
                                <button onclick="showAuditInPopup('${safeIssueId}')" class="btn btn-secondary" style="padding: 0.3rem; font-size: 0.75rem;"><i class="fa-solid fa-clock-rotate-left"></i> View Audit Trail</button>
                            </div>
                            <div id="audit-popup-${safeIssueId}" style="margin-top: 0.5rem; max-height: 150px; overflow-y: auto; display: none;"></div>
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
                        fillColor: "#d1264a",
                        color: "#c9a227",
                        weight: 2,
                        opacity: 0.9,
                        fillOpacity: 0.45
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

function renderWorkersList(workers) {
    const workersGrid = document.getElementById("workersGrid");
    if (!workersGrid) return;
    workersGrid.innerHTML = "";
    if (workers.length === 0) {
        workersGrid.innerHTML = `<div class="empty-state" style="grid-column: 1/-1; text-align: center; color: var(--text-muted); padding: 2rem;">No workers registered.</div>`;
        return;
    }
    const esc = window.escapeHtml || (s => s ? String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#039;') : '');
    workers.forEach(w => {
        const card = document.createElement("div");
        card.className = "glass-panel queue-card";
        const activeTasks = w.active_assignments ?? w.active_tasks ?? w.active_task_count ?? 0;
        const skillsText = (Array.isArray(w.skills) && w.skills.length > 0) ? w.skills.join(', ') : 'General Repair';
        const rating = Number(w.average_rating || 0).toFixed(1);
        const totalRatings = w.total_ratings || 0;
        card.innerHTML = `
            <div class="queue-card-header">
                <span class="badge" style="background: rgba(59, 130, 246, 0.2); color: var(--primary)">${w.is_available ? 'Available' : 'Busy'}</span>
                <strong style="color: var(--text-main);">${esc(w.name || 'Worker Crew')}</strong>
            </div>
            <div style="font-size: 0.85rem; color: var(--text-muted); display: flex; flex-direction: column; gap: 0.25rem; margin-top: 0.5rem;">
                <div><strong>Email:</strong> ${esc(w.email || '')}</div>
                <div><strong>Ward:</strong> ${esc(w.ward || 'N/A')}</div>
                <div><strong>Rating:</strong> ⭐ ${rating} (${totalRatings} ratings)</div>
                <div><strong>Active Tasks:</strong> ${activeTasks} / 5 limit</div>
                <div><strong>Skills:</strong> ${esc(skillsText)}</div>
            </div>
            <div style="margin-top: 0.75rem;">
                <button onclick="drawWorkerRouteOnOfficerMap('${esc(w._id)}')" class="btn btn-secondary" style="width: 100%; padding: 0.4rem; font-size: 0.8rem;">
                    <i class="fa-solid fa-route" style="color: var(--primary);"></i> View Route on Map
                </button>
            </div>
        `;
        workersGrid.appendChild(card);
    });
}

async function loadWorkers(force = false) {
    const workersGrid = document.getElementById("workersGrid");
    if (!workersGrid) return;

    if (!force) {
        const cached = getCached('workers');
        if (cached) {
            renderWorkersList(cached);
            return;
        }
    }

    if (typeof window.renderLoading === "function") {
        window.renderLoading(workersGrid, "Loading crew status...");
    } else {
        workersGrid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; padding: 2rem;"><i class="fa-solid fa-spinner fa-spin"></i> Loading crew status...</div>`;
    }

    try {
        const fetchFn = window.api || window.fetch;
        const res = await fetchFn("/api/workers");
        const data = (res && typeof res.json === "function" && !(res instanceof Response)) ? res : (res.data ? res : await res.json());

        if (data && data.success) {
            const workers = data.data || [];
            setCached('workers', workers);
            renderWorkersList(workers);
        } else {
            if (typeof window.renderErrorRetry === "function") {
                window.renderErrorRetry(workersGrid, "Failed to load worker profiles.", () => loadWorkers(true));
            } else {
                workersGrid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: var(--danger);">Failed to load worker profiles.</div>`;
            }
        }
    } catch (err) {
        console.error("Worker profiles fetch failed:", err);
        if (typeof window.renderErrorRetry === "function") {
            window.renderErrorRetry(workersGrid, "Failed to load worker profiles.", () => loadWorkers(true));
        } else {
            workersGrid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: var(--danger);">Failed to load worker profiles.</div>`;
        }
    }
}

let officerRouteLine;
async function drawWorkerRouteOnOfficerMap(workerId) {
    switchTab('map-view');
    try {
        const res = await fetch(`/api/map/route?worker_id=${workerId}`);
        const data = await res.json();
        if (data.success && data.data.length > 0) {
            if (officerRouteLine) map.removeLayer(officerRouteLine);

            const latlngs = [];
            data.data.forEach(stop => {
                if (stop.polyline) {
                    latlngs.push(...stop.polyline);
                }
            });

            if (latlngs.length > 0) {
                officerRouteLine = L.polyline(latlngs, { color: 'var(--primary)', weight: 5, opacity: 0.85 }).addTo(map);
                map.fitBounds(officerRouteLine.getBounds());
                if (typeof showToast === 'function') {
                    showToast(`Loaded route itinerary (${data.data.length} stops).`, "info");
                }
            }
        } else {
            if (typeof showToast === 'function') {
                showToast("No active assigned tasks for this worker to draw route.", "info");
            }
        }
    } catch (err) {
        console.error("Failed to draw worker route on map:", err);
    }
}

function renderBriefing(data) {
    if (!data) return;
    const textEl = document.getElementById("briefingText");
    if (textEl) textEl.innerText = data.briefing_text || '';

    const actionsEl = document.getElementById("recommendedActions");
    if (actionsEl) {
        actionsEl.innerHTML = "";
        const recs = data.recommended_actions || [];
        if (recs.length === 0) {
            actionsEl.innerHTML = "<li>No urgent recommendation actions.</li>";
        } else {
            recs.forEach(act => {
                const li = document.createElement("li");
                li.innerText = act;
                actionsEl.appendChild(li);
            });
        }
    }
}

async function loadBriefing(forceRefresh = false) {
    if (!forceRefresh) {
        const cached = getCached('briefing');
        if (cached) {
            renderBriefing(cached);
            return;
        }
    }
    try {
        const url = `/api/officer/briefing${forceRefresh ? '?refresh=true' : ''}`;
        const fetchFn = window.api || window.fetch;
        const res = await fetchFn(url);
        const data = (res && typeof res.json === "function" && !(res instanceof Response)) ? res : (res.data ? res : await res.json());
        if (data && data.success && data.data) {
            setCached('briefing', data.data);
            renderBriefing(data.data);
        }
    } catch (err) {
        console.error("Failed to load briefing", err);
    }
}

async function loadEmergencyBar() {
    try {
        const fetchFn = window.api || window.fetch;
        const res = await fetchFn("/api/issues?severity=critical");
        const data = (res && typeof res.json === "function" && !(res instanceof Response)) ? res : (res.data ? res : await res.json());
        const bar = document.getElementById("emergencyBar");
        const list = document.getElementById("emergencyList");
        if (!bar || !list) return;

        if (data && data.success && data.data && data.data.length > 0) {
            list.innerHTML = "";
            const esc = window.escapeHtml || (s => s ? String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#039;') : '');
            data.data.forEach(issue => {
                if (issue.is_emergency) {
                    const row = document.createElement("div");
                    row.style = "display: flex; justify-content: space-between; align-items: center; background: rgba(255,255,255,0.05); padding: 0.8rem; border-radius: 6px;";
                    row.innerHTML = `
                        <div>
                            <strong>${esc(issue.title || 'Civic Issue')} — ${esc(issue.emergency_category || 'EMERGENCY')}</strong>
                            <div style="font-size: 0.8rem; color: var(--text-muted);">Ward ${esc(issue.ward || '1')} · SLA: 1 hour</div>
                        </div>
                        <div style="display: flex; gap: 0.5rem;">
                            <button onclick="openAssignWorker('${esc(issue._id)}')" class="btn btn-primary" style="padding: 0.4rem 0.8rem; font-size: 0.75rem;"><i class="fa-solid fa-user-plus"></i> Assign Now</button>
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
            const esc = window.escapeHtml || (s => s ? String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#039;') : '');
            tagsEl.innerHTML = q.trim() !== "" ? `<span class="badge" style="background: rgba(56,189,248,0.2); color: var(--accent-primary);">NL Query: "${esc(q)}" <i class="fa-solid fa-times" onclick="clearSearch()" style="cursor:pointer; margin-left:5px;"></i></span>` : "";

            if (data.data.length === 0) {
                grid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: var(--text-muted); padding: 3rem;">No issues matching search criteria.</div>`;
                return;
            }

            data.data.forEach(issue => {
                const ageHours = Math.round((new Date() - new Date(issue.created_at)) / 3600000);
                const card = document.createElement("div");
                card.className = "glass-panel queue-card";
                const safeIssueId = encodeURIComponent(String(issue._id || ''));
                card.innerHTML = `
                    <div class="queue-card-header">
                        <span class="badge ${issue.severity === 'critical' ? 'badge-critical' : 'badge-severity'}">${esc(issue.severity)}</span>
                        <span class="badge badge-status">${esc(issue.status)}</span>
                    </div>
                    <h4 style="font-family: var(--font-display); font-weight: 700; font-size: 1.05rem;">${esc(issue.title)}</h4>
                    <div style="font-size: 0.85rem; color: var(--text-muted);">${esc(issue.description)}</div>
                    <div style="font-size: 0.85rem; color: var(--text-muted); display: flex; flex-direction: column; gap: 0.25rem;">
                        <div><strong>Category:</strong> ${esc(issue.category)}</div>
                        <div><strong>Ward:</strong> ${esc(issue.ward)}</div>
                        <div><strong>Priority Score:</strong> ${Number(issue.priority_score || 0)}</div>
                        <div><strong>Confirmations:</strong> ${Number(issue.confirmation_count || 0)} confirmations</div>
                    </div>
                    <div style="display: flex; gap: 0.5rem; margin-top: 0.75rem;">
                        <button onclick="openAssignWorker('${safeIssueId}')" class="btn btn-primary" style="width: 100%; padding: 0.5rem; font-size: 0.8rem;"><i class="fa-solid fa-user-plus"></i> Assign Worker</button>
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

function renderWardHealthList(wards) {
    const grid = document.getElementById("wardHealthGrid");
    if (!grid) return;
    grid.innerHTML = "";
    if (wards.length === 0) {
        grid.innerHTML = `<div class="empty-state" style="grid-column: 1/-1; text-align: center; color: var(--text-muted); padding: 2rem;">No ward data available.</div>`;
        return;
    }
    const esc = window.escapeHtml || (s => s ? String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#039;') : '');
    wards.forEach(w => {
        const score = w.ward_health_score ?? 100;
        let barColor = '#0f9d6b';
        if (score < 60) barColor = '#d1264a';
        else if (score < 80) barColor = '#d99a1a';

        const card = document.createElement("div");
        card.className = "glass-panel queue-card";
        card.style = "padding: 1.5rem; display:flex; flex-direction:column; gap:0.5rem;";
        card.innerHTML = `
            <h4 style="font-family: var(--font-display); font-weight:700;">${esc(w.ward || 'Ward')}</h4>
            <div style="font-size: 0.85rem; color:var(--text-muted);">Active Complaints: <strong>${w.count ?? 0}</strong></div>
            <div style="margin-top: 0.5rem;">
                <div style="display:flex; justify-content:space-between; font-size:0.85rem; margin-bottom: 0.25rem;">
                    <span>Health Score</span>
                    <span style="color: ${barColor}; font-weight:700;">${score}/100</span>
                </div>
                <div style="width:100%; height:10px; background:rgba(255,255,255,0.05); border-radius:5px; overflow:hidden;">
                    <div style="width:${Math.min(100, Math.max(0, score))}%; height:100%; background:${barColor};"></div>
                </div>
            </div>
        `;
        grid.appendChild(card);
    });
}

async function loadWardHealth(force = false) {
    const grid = document.getElementById("wardHealthGrid");
    if (!grid) return;

    if (!force) {
        const cached = getCached('ward_health');
        if (cached) {
            renderWardHealthList(cached);
            return;
        }
    }

    if (typeof window.renderLoading === "function") {
        window.renderLoading(grid, "Calculating health ratios...");
    } else {
        grid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; padding: 2rem;"><i class="fa-solid fa-spinner fa-spin"></i> Calculating health ratios...</div>`;
    }

    try {
        const fetchFn = window.api || window.fetch;
        const res = await fetchFn("/api/analytics/by-ward");
        const data = (res && typeof res.json === "function" && !(res instanceof Response)) ? res : (res.data ? res : await res.json());
        if (data && data.success) {
            const wards = data.data || [];
            setCached('ward_health', wards);
            renderWardHealthList(wards);
        } else {
            if (typeof window.renderErrorRetry === "function") {
                window.renderErrorRetry(grid, "Failed to load health statistics.", () => loadWardHealth(true));
            } else {
                grid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: var(--danger);">Failed to load health statistics.</div>`;
            }
        }
    } catch (err) {
        console.error("Ward health fetch failed:", err);
        if (typeof window.renderErrorRetry === "function") {
            window.renderErrorRetry(grid, "Failed to load health statistics.", () => loadWardHealth(true));
        } else {
            grid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: var(--danger);">Failed to load health statistics.</div>`;
        }
    }
}

function renderRecurringList(hotspots) {
    const grid = document.getElementById("recurringGrid");
    if (!grid) return;
    grid.innerHTML = "";
    if (hotspots.length === 0) {
        grid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: var(--text-muted); padding: 3rem;">No recurring hotspots detected yet.</div>`;
        return;
    }
    const esc = window.escapeHtml || (s => s ? String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#039;') : '');
    hotspots.forEach(h => {
        const card = document.createElement("div");
        card.className = "glass-panel queue-card";
        const cat = esc(String(h.category || 'civic').toUpperCase());
        const firstDate = h.first_occurrence ? new Date(h.first_occurrence).toLocaleDateString() : 'N/A';
        const lastDate = h.last_occurrence ? new Date(h.last_occurrence).toLocaleDateString() : 'N/A';
        card.innerHTML = `
            <div class="queue-card-header">
                <span class="badge badge-critical"><i class="fa-solid fa-arrows-spin"></i> RECURRING</span>
                <strong style="color:var(--text-main);">${cat}</strong>
            </div>
            <div style="font-size: 0.85rem; color: var(--text-muted); display: flex; flex-direction: column; gap: 0.25rem; margin-top: 0.5rem;">
                <div><strong>Ward:</strong> ${esc(h.ward || 'N/A')}</div>
                <div><strong>Total Occurrences:</strong> ${h.total_occurrences ?? 1} times</div>
                <div><strong>First Reported:</strong> ${esc(firstDate)}</div>
                <div><strong>Latest:</strong> ${esc(lastDate)}</div>
            </div>
        `;
        grid.appendChild(card);
    });
}

async function loadRecurringHotspots(force = false) {
    const grid = document.getElementById("recurringGrid");
    if (!grid) return;

    if (!force) {
        const cached = getCached('recurring');
        if (cached) {
            renderRecurringList(cached);
            return;
        }
    }

    if (typeof window.renderLoading === "function") {
        window.renderLoading(grid, "Scanning hotspots...");
    } else {
        grid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; padding: 2rem;"><i class="fa-solid fa-spinner fa-spin"></i> Scanning hotspots...</div>`;
    }

    try {
        const fetchFn = window.api || window.fetch;
        const res = await fetchFn("/api/analytics/recurring");
        const data = (res && typeof res.json === "function" && !(res instanceof Response)) ? res : (res.data ? res : await res.json());
        if (data && data.success) {
            const hotspots = data.data || [];
            setCached('recurring', hotspots);
            renderRecurringList(hotspots);
        } else {
            if (typeof window.renderErrorRetry === "function") {
                window.renderErrorRetry(grid, "Failed to load recurring hotspots.", () => loadRecurringHotspots(true));
            } else {
                grid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: var(--danger);">Failed to load recurring hotspots.</div>`;
            }
        }
    } catch (err) {
        console.error("Recurring hotspots fetch failed:", err);
        if (typeof window.renderErrorRetry === "function") {
            window.renderErrorRetry(grid, "Failed to load recurring hotspots.", () => loadRecurringHotspots(true));
        } else {
            grid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: var(--danger);">Failed to load recurring hotspots.</div>`;
        }
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

                let color = '#d1264a'; // Jewel Ruby
                if (risk === 'medium') color = '#d99a1a'; // Amber Gold
                else if (risk === 'low') color = '#0f9d6b'; // Jewel Emerald

                const circle = L.circle([lat, lng], {
                    radius: 500, // 500m radius
                    color: '#c9a227', // Imperial Gold outline
                    weight: 1.5,
                    fillColor: color,
                    fillOpacity: 0.25
                }).addTo(map);

                circle.bindPopup(`
                    <div style="font-family: 'Plus Jakarta Sans', sans-serif; padding: 4px;">
                        <h4 style="margin:0 0 5px 0; color: #d1264a; font-family: 'Playfair Display', serif; font-weight:700;"><i class="fa-solid fa-triangle-exclamation"></i> Predicted Hotspot</h4>
                        <p style="margin:0; font-size:0.8rem; color: #5b5a72;">Category: <strong>${category.toUpperCase()}</strong></p>
                        <p style="margin:0; font-size:0.8rem; color: #5b5a72;">Risk Level: <strong>${risk.toUpperCase()}</strong></p>
                        <p style="margin:0; font-size:0.8rem; color: #5b5a72;">Recurrence Rate: <strong>${h.recurrence_rate}/month</strong></p>
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

async function runWorkerSim() {
    const ward = document.getElementById("simWard").value.trim();
    const department = document.getElementById("simDept").value;
    const additional_workers = parseInt(document.getElementById("simWorkerCount").value) || 1;
    const resultDiv = document.getElementById("workerSimResult");

    resultDiv.innerHTML = `<div style="text-align:center; color: var(--text-muted);"><i class="fa-solid fa-spinner fa-spin"></i> Running simulation…</div>`;
    resultDiv.style.display = "block";

    try {
        const res = await fetch("/api/simulate/worker-addition", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ ward: ward || "", department, additional_workers })
        });
        const data = await res.json();
        if (!data.success) {
            resultDiv.innerHTML = `<p style="color: var(--danger);">${data.error?.message || "Simulation failed."}</p>`;
            return;
        }
        const d = data.data;
        resultDiv.innerHTML = `
            <div style="border-top: 1px solid rgba(255,255,255,0.08); padding-top: 1rem; display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem;">
                <div class="sim-metric"><span class="sim-label">Current Workers</span><span class="sim-value">${d.current_workers}</span></div>
                <div class="sim-metric"><span class="sim-label">After Addition</span><span class="sim-value" style="color:var(--primary)">${d.current_workers + d.additional_workers}</span></div>
                <div class="sim-metric"><span class="sim-label">Avg Resolution Now</span><span class="sim-value">${d.current_avg_resolution_hours}h</span></div>
                <div class="sim-metric"><span class="sim-label">Estimated New Avg</span><span class="sim-value" style="color:var(--success)">${d.estimated_avg_resolution_hours}h</span></div>
                <div class="sim-metric"><span class="sim-label">Open Complaints</span><span class="sim-value">${d.open_complaints}</span></div>
                <div class="sim-metric"><span class="sim-label">Clearance Estimate</span><span class="sim-value">${d.estimated_clearance_hours}h</span></div>
                <div class="sim-metric"><span class="sim-label">SLA Compliance Now</span><span class="sim-value">${d.current_sla_compliance_pct}%</span></div>
                <div class="sim-metric"><span class="sim-label">Estimated New SLA</span><span class="sim-value" style="color:var(--success)">${d.estimated_sla_compliance_pct}%</span></div>
            </div>`;
    } catch (err) {
        resultDiv.innerHTML = `<p style="color: var(--danger);">Network error. Please try again.</p>`;
        console.error("Worker sim error:", err);
    }
}

async function runPrioritySim() {
    const category = document.getElementById("simCategory").value;
    const resultDiv = document.getElementById("prioritySimResult");

    resultDiv.innerHTML = `<div style="text-align:center; color: var(--text-muted);"><i class="fa-solid fa-spinner fa-spin"></i> Running simulation…</div>`;
    resultDiv.style.display = "block";

    try {
        const res = await fetch("/api/simulate/category-priority", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ category })
        });
        const data = await res.json();
        if (!data.success) {
            resultDiv.innerHTML = `<p style="color: var(--danger);">${data.error?.message || "Simulation failed."}</p>`;
            return;
        }
        const d = data.data;
        let otherRows = d.other_categories_impact.map(o =>
            `<tr>
                <td style="padding: 0.4rem 0.5rem; text-transform: capitalize;">${o.category}</td>
                <td style="padding: 0.4rem 0.5rem; text-align:right;">${o.current_avg_hours}h</td>
                <td style="padding: 0.4rem 0.5rem; text-align:right; color: var(--danger);">${o.estimated_avg_hours}h</td>
            </tr>`
        ).join("");
        resultDiv.innerHTML = `
            <div style="border-top: 1px solid rgba(255,255,255,0.08); padding-top: 1rem;">
                <p style="color: var(--success); font-weight: 600;">
                    <i class="fa-solid fa-circle-check"></i>
                    <span style="text-transform:capitalize;">${d.prioritized_category}</span> resolution improves by
                    <strong>${d.estimated_resolution_improvement_hours}h</strong>
                </p>
                <p style="color: var(--warning); font-size: 0.85rem; margin-top: 0.5rem;">
                    <i class="fa-solid fa-triangle-exclamation"></i> SLA breach risk on other categories: +${d.sla_risk_increase} issues
                </p>
                <table style="width: 100%; margin-top: 1rem; font-size: 0.85rem; border-collapse: collapse;">
                    <thead>
                        <tr style="color: var(--text-muted);">
                            <th style="text-align:left; padding: 0.3rem 0.5rem;">Category</th>
                            <th style="text-align:right; padding: 0.3rem 0.5rem;">Current Avg</th>
                            <th style="text-align:right; padding: 0.3rem 0.5rem;">Estimated</th>
                        </tr>
                    </thead>
                    <tbody>${otherRows}</tbody>
                </table>
            </div>`;
    } catch (err) {
        resultDiv.innerHTML = `<p style="color: var(--danger);">Network error. Please try again.</p>`;
        console.error("Priority sim error:", err);
    }
}

async function inspectCefap(issueId) {
    try {
        const res = await fetch(`/api/issues/${issueId}`);
        const data = await res.json();
        if (data.success && data.data) {
            renderCefapCard(data.data);
            const card = document.getElementById('cefap-card');
            if (card) card.scrollIntoView({ behavior: 'smooth' });
        }
    } catch (err) {
        console.error("Failed to fetch issue CEFAP data:", err);
    }
}

function renderCefapCard(complaint) {
    const card = document.getElementById('cefap-card');
    if (!card) return;

    if (!complaint || !complaint.cips_score) {
        card.style.display = 'none';
        return;
    }

    card.style.display = 'block';

    // Priority badge
    const badge = document.getElementById('cefap-priority-badge');
    if (badge) {
        const priorityColors = {
            'P1': '#d1264a', // Jewel Ruby
            'P2': '#e0701a', // Burnt Orange
            'P3': '#d99a1a', // Amber Gold
            'P4': '#2f5bd8'  // Jewel Sapphire
        };
        const p = complaint.priority || 'P3';
        badge.innerText = p;
        badge.style.backgroundColor = priorityColors[p] || '#6b6a8a';
        badge.style.color = '#ffffff';
    }

    // CIPS gauge
    const cipsValue = document.getElementById('cefap-cips-value');
    if (cipsValue) cipsValue.innerText = Number(complaint.cips_score).toFixed(2);

    const cipsBar = document.getElementById('cefap-cips-bar');
    if (cipsBar) {
        const pct = Math.round(complaint.cips_score * 100);
        cipsBar.style.width = pct + '%';
        cipsBar.style.backgroundColor =
            complaint.cips_score >= 0.75 ? '#d1264a' :
                complaint.cips_score >= 0.50 ? '#e0701a' :
                    complaint.cips_score >= 0.25 ? '#d99a1a' : '#2f5bd8';
    }

    // 6 Signals breakdown
    const container = document.getElementById('cefap-signals-container');
    if (container && complaint.signals) {
        const signalLabels = {
            hazard_severity: 'Hazard Severity',
            location_impact: 'Location Impact',
            citizen_impact: 'Citizen Impact',
            duplicate_surge: 'Duplicate Surge',
            historical_reopen_rate: 'Historical Reopen Rate',
            ward_health_penalty: 'Ward Health Penalty',
            text_severity: 'Text Severity',
            image_severity: 'Image Severity',
            corroboration: 'Corroboration',
            recurrence: 'Recurrence',
            sla_risk: 'SLA Risk'
        };

        container.innerHTML = Object.entries(complaint.signals).map(([key, rawVal]) => {
            if (rawVal === null || rawVal === undefined) return '';
            const val = Number(rawVal) || 0;
            const label = signalLabels[key] || key.replace(/_/g, ' ');
            const pct = Math.round(val * 100);
            return `
                <div class="d-flex align-items-center mb-1" style="display:flex; align-items:center; margin-bottom:4px; font-size:12px;">
                    <span style="width:160px; color:var(--text-secondary); text-transform:capitalize;">${label}</span>
                    <div style="flex:1; height:6px; background:rgba(201, 162, 39, 0.15); border-radius:99px; margin:0 8px; overflow:hidden;">
                        <div style="width:${pct}%; height:100%; background:var(--primary); border-radius:99px;"></div>
                    </div>
                    <span style="width:35px; text-align:right; font-weight:600; color:var(--text-main);">${val.toFixed(2)}</span>
                </div>
            `;
        }).join('');
    }

    // Evidence reliability & agreement
    const eVal = document.getElementById('cefap-e-value');
    if (eVal) eVal.innerText = complaint.evidence_reliability !== undefined && complaint.evidence_reliability !== null ? Number(complaint.evidence_reliability).toFixed(2) : '1.00';

    const agreeVal = document.getElementById('cefap-agreement-value');
    if (agreeVal) agreeVal.innerText = complaint.evidence_agreement !== undefined && complaint.evidence_agreement !== null ? Number(complaint.evidence_agreement).toFixed(2) : '1.00';

    // CTVE flag
    const ctveFlag = document.getElementById('cefap-ctve-flag');
    if (ctveFlag) ctveFlag.style.display = complaint.ctve_triggered ? 'block' : 'none';

    // Monsoon flag
    const monsoonFlag = document.getElementById('cefap-monsoon-flag');
    if (monsoonFlag) monsoonFlag.style.display = complaint.monsoon_active ? 'block' : 'none';
}

// ── Admin Announcement Broadcast Center ──────────────────────────────
function updateAnnouncementPreview() {
    const title = (document.getElementById('annTitle')?.value || '').trim() || 'Notice Title';
    const body = (document.getElementById('annBody')?.value || '').trim() || 'Notice body content will be shown here.';
    const severity = (document.getElementById('annSeverity')?.value || 'info').toLowerCase();
    const audience = (document.getElementById('annAudience')?.value || 'both').toLowerCase();
    const pinned = Boolean(document.getElementById('annPinned')?.checked);

    const titleEl = document.getElementById('previewTitle');
    const bodyEl = document.getElementById('previewBody');
    const badgeEl = document.getElementById('previewSeverityBadge');
    const audEl = document.getElementById('previewAudienceBadge');
    const container = document.getElementById('announcementPreviewContainer');

    if (titleEl) titleEl.textContent = (pinned ? '📌 ' : '') + title;
    if (bodyEl) bodyEl.textContent = body;

    const colors = {
        info: { border: '#3b82f6', bg: 'rgba(59, 130, 246, 0.15)', text: '#60a5fa' },
        warning: { border: '#f59e0b', bg: 'rgba(245, 158, 11, 0.15)', text: '#fbbf24' },
        critical: { border: '#ef4444', bg: 'rgba(239, 68, 68, 0.15)', text: '#f87171' }
    };
    const c = colors[severity] || colors.info;

    if (badgeEl) {
        badgeEl.textContent = severity.toUpperCase();
        badgeEl.style.background = c.bg;
        badgeEl.style.color = c.text;
    }
    if (container) {
        container.style.borderLeftColor = c.border;
    }
    if (audEl) {
        audEl.textContent = audience === 'both' ? '👥 Both' : (audience === 'citizen' ? '👤 Citizens' : '🛠️ Workers');
    }
}

async function handleBroadcastAnnouncement(e) {
    if (e && e.preventDefault) e.preventDefault();
    const titleInput = document.getElementById('annTitle');
    const bodyInput = document.getElementById('annBody');
    const severityInput = document.getElementById('annSeverity');
    const audienceInput = document.getElementById('annAudience');
    const durationInput = document.getElementById('annDuration');
    const pinnedInput = document.getElementById('annPinned');
    const statusDiv = document.getElementById('annBroadcastStatus');
    const submitBtn = document.getElementById('btnSubmitBroadcast');

    const title = (titleInput?.value || '').trim();
    const body = (bodyInput?.value || '').trim();
    const severity = severityInput?.value || 'info';
    const audience = audienceInput?.value || 'both';
    const expiresInHours = parseInt(durationInput?.value || '24', 10);
    const pinned = Boolean(pinnedInput?.checked);

    if (!title || !body) return;

    const confirmMsg = `Confirm broadcast of this ${severity.toUpperCase()} notice to ${audience.toUpperCase()}?`;
    if (!window.confirm(confirmMsg)) {
        return;
    }

    if (submitBtn) submitBtn.disabled = true;
    if (statusDiv) {
        statusDiv.style.display = 'block';
        statusDiv.style.background = 'rgba(59, 130, 246, 0.1)';
        statusDiv.style.color = '#60a5fa';
        statusDiv.textContent = 'Broadcasting notice...';
    }

    try {
        const res = await api('/api/admin/announcements', {
            method: 'POST',
            body: JSON.stringify({
                title,
                body,
                severity,
                audience,
                expires_in_hours: expiresInHours,
                pinned
            })
        });

        const data = await res.json();
        if (data.success) {
            if (statusDiv) {
                statusDiv.style.background = 'rgba(16, 185, 129, 0.15)';
                statusDiv.style.color = '#34d399';
                statusDiv.textContent = 'Notice broadcast successfully across municipal channels.';
            }
            if (titleInput) titleInput.value = '';
            if (bodyInput) bodyInput.value = '';
            if (pinnedInput) pinnedInput.checked = false;
            updateAnnouncementPreview();
            loadAdminAnnouncements();
            setTimeout(() => {
                if (statusDiv) statusDiv.style.display = 'none';
            }, 4000);
        } else {
            throw new Error((data.error && data.error.message) || 'Broadcast failed.');
        }
    } catch (err) {
        if (statusDiv) {
            statusDiv.style.background = 'rgba(239, 68, 68, 0.15)';
            statusDiv.style.color = '#f87171';
            statusDiv.textContent = err.message || 'Broadcast failed.';
        }
    } finally {
        if (submitBtn) submitBtn.disabled = false;
    }
}

async function loadAdminAnnouncements() {
    const listContainer = document.getElementById('announcementsHistoryList');
    if (!listContainer) return;

    try {
        const res = await api('/api/admin/announcements');
        const json = await res.json();
        const items = json.data || [];

        listContainer.textContent = '';

        if (items.length === 0) {
            const emptyP = document.createElement('p');
            emptyP.style.color = 'var(--text-muted)';
            emptyP.style.fontSize = '0.85rem';
            emptyP.textContent = 'No announcements recorded.';
            listContainer.appendChild(emptyP);
            return;
        }

        items.forEach(item => {
            const card = document.createElement('div');
            card.style.padding = '0.85rem 1rem';
            card.style.borderRadius = '6px';
            card.style.background = 'rgba(255, 255, 255, 0.03)';
            card.style.border = '1px solid rgba(255, 255, 255, 0.08)';
            card.style.display = 'flex';
            card.style.justifyContent = 'space-between';
            card.style.alignItems = 'flex-start';
            card.style.gap = '1rem';

            const leftDiv = document.createElement('div');
            leftDiv.style.flex = '1';

            const headerRow = document.createElement('div');
            headerRow.style.display = 'flex';
            headerRow.style.alignItems = 'center';
            headerRow.style.gap = '0.5rem';
            headerRow.style.marginBottom = '0.35rem';

            const badge = document.createElement('span');
            badge.style.padding = '0.15rem 0.45rem';
            badge.style.borderRadius = '4px';
            badge.style.fontSize = '0.7rem';
            badge.style.fontWeight = '700';
            badge.style.textTransform = 'uppercase';
            const sev = (item.severity || 'info').toLowerCase();
            badge.textContent = sev;
            badge.style.background = sev === 'critical' ? 'rgba(239,68,68,0.2)' : (sev === 'warning' ? 'rgba(245,158,11,0.2)' : 'rgba(59,130,246,0.2)');
            badge.style.color = sev === 'critical' ? '#f87171' : (sev === 'warning' ? '#fbbf24' : '#60a5fa');
            headerRow.appendChild(badge);

            const titleStrong = document.createElement('strong');
            titleStrong.style.fontSize = '0.9rem';
            titleStrong.style.color = 'var(--text-primary)';
            titleStrong.textContent = (item.pinned ? '📌 ' : '') + (item.title || 'Notice');
            headerRow.appendChild(titleStrong);

            if (item.status === 'retracted') {
                const retBadge = document.createElement('span');
                retBadge.style.padding = '0.1rem 0.4rem';
                retBadge.style.borderRadius = '4px';
                retBadge.style.fontSize = '0.65rem';
                retBadge.style.background = 'rgba(148,163,184,0.2)';
                retBadge.style.color = '#94a3b8';
                retBadge.textContent = 'RETRACTED';
                headerRow.appendChild(retBadge);
            }

            leftDiv.appendChild(headerRow);

            const bodyP = document.createElement('p');
            bodyP.style.fontSize = '0.82rem';
            bodyP.style.color = 'var(--text-muted)';
            bodyP.style.margin = '0 0 0.4rem 0';
            bodyP.style.lineHeight = '1.4';
            bodyP.textContent = item.body || '';
            leftDiv.appendChild(bodyP);

            const metaSpan = document.createElement('div');
            metaSpan.style.fontSize = '0.75rem';
            metaSpan.style.color = '#64748b';
            metaSpan.textContent = `Audience: ${item.audience || 'both'} • Read by ${item.read_count || 0} users • Created: ${item.created_at ? new Date(item.created_at).toLocaleString() : 'Recent'}`;
            leftDiv.appendChild(metaSpan);

            card.appendChild(leftDiv);

            if (item.status === 'active') {
                const retractBtn = document.createElement('button');
                retractBtn.className = 'btn-danger';
                retractBtn.style.padding = '0.35rem 0.75rem';
                retractBtn.style.fontSize = '0.75rem';
                retractBtn.style.border = 'none';
                retractBtn.style.borderRadius = '4px';
                retractBtn.style.background = 'rgba(239, 68, 68, 0.2)';
                retractBtn.style.color = '#f87171';
                retractBtn.style.cursor = 'pointer';
                retractBtn.textContent = 'Retract';
                retractBtn.onclick = () => retractAnnouncement(item._id);
                card.appendChild(retractBtn);
            }

            listContainer.appendChild(card);
        });
    } catch (err) {
        listContainer.textContent = '';
        const errP = document.createElement('p');
        errP.style.color = '#f87171';
        errP.style.fontSize = '0.85rem';
        errP.textContent = 'Failed to load announcements: ' + err.message;
        listContainer.appendChild(errP);
    }
}

async function retractAnnouncement(annId) {
    if (!window.confirm('Are you sure you want to retract this active broadcast immediately?')) {
        return;
    }
    try {
        const res = await api(`/api/admin/announcements/${annId}/retract`, { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            loadAdminAnnouncements();
        } else {
            alert((data.error && data.error.message) || 'Failed to retract.');
        }
    } catch (err) {
        alert(err.message || 'Failed to retract.');
    }
}


