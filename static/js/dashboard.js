/* SmartCivic - Dashboard Widgets */

const Dashboard = {
  loadCommunityData: async function(communityId) {
    const res = await apiFetch(`/api/dashboard/community/${communityId}`);
    if (!res?.success) return;
    
    const data = res.data;
    Dashboard.renderGauge(data.community_score);
    Dashboard.renderStatsGrid(data);
    Dashboard.renderRecentIssues(data.recent_issues);
    Dashboard.renderAnnouncements(data.active_announcements);
  },

  loadAuthorityData: async function(communityId) {
    const res = await apiFetch(`/api/dashboard/authority/${communityId}`);
    if (!res?.success) return;
    
    const data = res.data;
    // Base stats
    Dashboard.renderGauge(data.community_score);
    Dashboard.renderStatsGrid(data);
    Dashboard.renderRecentIssues(data.recent_issues);
    Dashboard.renderAnnouncements(data.active_announcements);
    
    // Authority specific widgets
    const pendingUsersContainer = document.getElementById('pending-users-count');
    if (pendingUsersContainer) pendingUsersContainer.textContent = data.pending_users_count;
    
    const urgentUnassignedContainer = document.getElementById('urgent-unassigned-count');
    if (urgentUnassignedContainer) urgentUnassignedContainer.textContent = data.urgent_unassigned;
    
    Dashboard.renderActiveWorkers(data.active_workers);
    Dashboard.renderActiveRoutes(data.active_routes);
    Dashboard.renderRecommendations(data.recommendations);
  },

  renderGauge: function(score) {
    const gauge = document.getElementById('community-score-gauge');
    const value = document.getElementById('community-score-value');
    if (!gauge || !value) return;
    
    value.textContent = score;
    
    // Calculate color based on score
    let scoreColor = 'var(--score-low)';
    if (score >= 80) {
      scoreColor = 'var(--score-high)';
    } else if (score >= 50) {
      scoreColor = 'var(--score-mid)';
    }
    
    gauge.style.setProperty('--score-color', scoreColor);
    
    // Calculate conic degree
    const deg = (score / 100) * 360;
    gauge.style.background = `conic-gradient(${scoreColor} ${deg}deg, var(--neutral-200) ${deg}deg)`;
  },

  renderStatsGrid: function(data) {
    const categoriesDiv = document.getElementById('issues-by-category');
    if (categoriesDiv) {
      let catHtml = '';
      if (Object.keys(data.issues_by_category).length === 0) {
        catHtml = `<div style="color:var(--neutral-600); font-size:0.9rem;">No reported issues.</div>`;
      } else {
        Object.entries(data.issues_by_category).forEach(([cat, count]) => {
          catHtml += `
            <div style="display:flex; justify-content:space-between; margin-bottom:8px; font-size:0.9rem;">
              <span style="text-transform:capitalize;">${cat}</span>
              <span style="font-weight:bold;">${count}</span>
            </div>
          `;
        });
      }
      categoriesDiv.innerHTML = catHtml;
    }
    
    const resolutionRateDiv = document.getElementById('resolution-rate');
    if (resolutionRateDiv) resolutionRateDiv.textContent = `${data.resolution_rate}%`;
    
    const avgTimeDiv = document.getElementById('avg-resolution-time');
    if (avgTimeDiv) avgTimeDiv.textContent = `${data.avg_resolution_time_hours} hrs`;
    
    const slaDiv = document.getElementById('sla-compliance-summary');
    if (slaDiv) {
      const summary = data.sla_status_summary;
      slaDiv.innerHTML = `
        <div style="display:flex; flex-direction:column; gap:4px; font-size:0.9rem;">
          <div style="display:flex; justify-content:space-between;"><span>On Time:</span><span style="font-weight:bold; color:var(--success)">${summary.on_time}</span></div>
          <div style="display:flex; justify-content:space-between;"><span>Overdue:</span><span style="font-weight:bold; color:var(--danger)">${summary.overdue}</span></div>
          <div style="display:flex; justify-content:space-between;"><span>Breached:</span><span style="font-weight:bold; color:var(--warning)">${summary.breached}</span></div>
        </div>
      `;
    }
    
    const topReportersDiv = document.getElementById('top-reporters-list');
    if (topReportersDiv) {
      let repHtml = '';
      data.top_reporters.forEach(rep => {
        repHtml += `
          <div style="display:flex; justify-content:space-between; margin-bottom:8px; font-size:0.9rem;">
            <span>${rep.name_or_anon}</span>
            <span style="font-weight:bold; color:var(--primary);">${rep.count} reports</span>
          </div>
        `;
      });
      topReportersDiv.innerHTML = repHtml || 'No contributors yet.';
    }
  },

  renderRecentIssues: function(issues) {
    const list = document.getElementById('recent-issues-list');
    if (!list) return;
    
    if (issues.length === 0) {
      list.innerHTML = `<div style="text-align:center; padding:20px; color:var(--neutral-600)" data-i18n="empty_no_issues">No issues reported yet.</div>`;
      return;
    }
    
    let html = '';
    issues.forEach(iss => {
      const slaClass = getSLAClass(iss.sla_status);
      html += `
        <div class="card" style="margin-bottom:12px; padding:15px; cursor:pointer;" onclick="window.location.href='/issues/${iss._id}'">
          <div style="display:flex; justify-content:space-between; align-items:start; margin-bottom:6px;">
            <h4 style="font-size:1rem; font-weight:600;">${iss.title}</h4>
            <span class="badge-cat cat-${iss.category}">${iss.category}</span>
          </div>
          <p style="font-size:0.85rem; color:var(--neutral-700); margin-bottom:8px; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden;">
            ${iss.description}
          </p>
          <div style="display:flex; justify-content:space-between; align-items:center; font-size:0.8rem; color:var(--neutral-600)">
            <span>Reporter: ${iss.reporter_name} · ${timeAgo(iss.created_at)}</span>
            <span style="padding:2px 6px; border-radius:4px; font-size:0.75rem;" class="status-badge">${iss.status.replace('_', ' ')}</span>
          </div>
        </div>
      `;
    });
    list.innerHTML = html;
  },

  renderAnnouncements: function(anns) {
    const container = document.getElementById('announcements-container');
    if (!container) return;
    
    if (anns.length === 0) {
      container.innerHTML = `<div style="color:var(--neutral-600); font-size:0.9rem;">No active announcements.</div>`;
      return;
    }
    
    let html = '';
    anns.forEach(ann => {
      html += `
        <div style="padding:10px 0; border-bottom:1px solid var(--neutral-200);">
          <h4 style="font-size:0.95rem; font-weight:600; color:var(--neutral-900)">📢 ${ann.title}</h4>
          <p style="font-size:0.85rem; color:var(--neutral-700); margin-top:4px;">${ann.body}</p>
          <span style="font-size:0.75rem; color:var(--neutral-400); display:block; margin-top:4px;">Posted ${timeAgo(ann.created_at)}</span>
        </div>
      `;
    });
    container.innerHTML = html;
  },

  renderActiveWorkers: function(workers) {
    const container = document.getElementById('active-workers-list');
    if (!container) return;
    
    if (workers.length === 0) {
      container.innerHTML = `<div style="color:var(--neutral-600); font-size:0.9rem;">No active field workers.</div>`;
      return;
    }
    
    let html = '';
    workers.forEach(w => {
      html += `
        <div class="hotspot-card" style="background:var(--neutral-100);">
          <div class="hotspot-info">
            <span class="hotspot-name">${w.name}</span>
            <span class="hotspot-meta">Assigned Issues: ${w.active_issues}</span>
          </div>
          ${w.last_lat ? `<button class="btn btn-secondary" style="padding:4px 8px; font-size:0.8rem;" onclick="CivicMap.init('auth-map', ${w.last_lat}, ${w.last_lng}, 15); CivicMap.addMarker(${w.last_lat}, ${w.last_lng}, 'Worker ${w.name}');">Locate</button>` : '<span style="font-size:0.75rem; color:var(--neutral-400)">No GPS</span>'}
        </div>
      `;
    });
    container.innerHTML = html;
  },

  renderActiveRoutes: function(routes) {
    const container = document.getElementById('active-routes-list');
    if (!container) return;
    
    if (routes.length === 0) {
      container.innerHTML = `<div style="color:var(--neutral-600); font-size:0.9rem;">No active routes.</div>`;
      return;
    }
    
    let html = '';
    routes.forEach(r => {
      html += `
        <div style="padding:10px; border-bottom:1px solid var(--neutral-200); font-size:0.85rem; display:flex; justify-content:space-between; align-items:center; gap:10px;">
          <div style="flex:1;">
            <div style="display:flex; justify-content:space-between; font-weight:600; margin-bottom:4px;">
              <span>Worker: ${r.worker_name}</span>
              <span style="color:var(--primary)">${r.total_distance_km} km</span>
            </div>
            <div style="display:flex; justify-content:space-between; color:var(--neutral-600)">
              <span>Issues: ${r.issue_count}</span>
              <span>Assigned ${timeAgo(r.created_at)}</span>
            </div>
          </div>
          <button class="btn btn-secondary" style="padding:4px 8px; font-size:0.75rem; background:var(--danger-light); color:var(--danger); border:1px solid var(--danger-light);" onclick="Dashboard.cancelRoute('${r.route_id}')">Unassign</button>
        </div>
      `;
    });
    container.innerHTML = html;
  },

  cancelRoute: async function(routeId) {
    if (confirm("Are you sure you want to unassign this route? All assigned issues will be returned to the validated queue.")) {
      const res = await apiFetch(`/api/workers/route/${routeId}/cancel`, { method: 'PUT' });
      if (res?.success) {
        showToast("Route unassigned successfully!", "success");
        const user = Auth.getUser();
        if (user) {
          Dashboard.loadAuthorityData(user.community_id);
        }
      } else if (res) {
        showToast(res.message, "error");
      }
    }
  },

  loadHotspots: async function(communityId) {
    const res = await apiFetch(`/api/dashboard/hotspots/${communityId}`);
    if (!res?.success) return;
    
    const list = document.getElementById('hotspots-list');
    if (!list) return;
    
    const hotspots = res.data;
    if (hotspots.length === 0) {
      list.innerHTML = `<div style="color:var(--neutral-600); font-size:0.9rem;">No clusters identified.</div>`;
      return;
    }
    
    let html = '';
    hotspots.forEach((h, index) => {
      html += `
        <div class="hotspot-card" onclick="CivicMap.init('auth-map', ${h.center_lat}, ${h.center_lng}, 16); CivicMap.addMarker(${h.center_lat}, ${h.center_lng}, 'Cluster center for ${h.count} issues', true);">
          <div class="hotspot-info">
            <span class="hotspot-name">Cluster #${index+1} (${h.top_category})</span>
            <span class="hotspot-meta">${h.count} issues nearby</span>
          </div>
          <span class="hotspot-badge">Priority: ${h.priority}</span>
        </div>
      `;
      
      // Plot on dashboard map if map exists
      if (typeof CivicMap !== 'undefined' && CivicMap.map) {
        CivicMap.addMarker(h.center_lat, h.center_lng, `Cluster #${index+1}: ${h.count} ${h.top_category} issues. Priority ${h.priority}`, true);
      }
    });
    list.innerHTML = html;
  },

  triggerExport: async function(communityId) {
    const dateFrom = document.getElementById('export-date-from')?.value || '';
    const dateTo = document.getElementById('export-date-to')?.value || '';
    
    const res = await apiFetch(`/api/dashboard/export/${communityId}?date_from=${dateFrom}&date_to=${dateTo}`);
    if (!res?.success) return;
    
    const data = res.data;
    
    // Render printable section
    let printArea = document.getElementById('print-area');
    if (!printArea) {
      printArea = document.createElement('div');
      printArea.id = 'print-area';
      printArea.style.display = 'none';
      document.body.appendChild(printArea);
    }
    
    let tableRows = '';
    data.issues.forEach(iss => {
      tableRows += `
        <tr>
          <td>${iss.title}</td>
          <td>${iss.category}</td>
          <td>${iss.address}</td>
          <td>${iss.severity} / 5</td>
          <td>${iss.status}</td>
          <td>${timeAgo(iss.created_at)}</td>
        </tr>
      `;
    });
    
    printArea.innerHTML = `
      <div class="print-header">
        <h1 class="print-title">SmartCivic Analytics Report</h1>
        <p class="print-meta">Community: ${data.community_name} (${data.city}, ${data.state}) | Export Time: ${new Date(data.export_time).toLocaleString()}</p>
        <p class="print-meta">Filter Range: ${data.date_from || 'Beginning'} to ${data.date_to || 'Now'}</p>
      </div>
      
      <div style="display:flex; justify-content:space-around; margin-bottom:30px; border:1px solid #ccc; padding:15px; text-align:center;">
        <div><h3>Total Reported</h3><p style="font-size:20pt; font-weight:bold;">${data.total_count}</p></div>
        <div><h3>Resolved</h3><p style="font-size:20pt; font-weight:bold; color:green;">${data.resolved_count}</p></div>
        <div><h3>Open</h3><p style="font-size:20pt; font-weight:bold; color:orange;">${data.open_count}</p></div>
      </div>
      
      <table>
        <thead>
          <tr>
            <th>Title</th>
            <th>Category</th>
            <th>Address</th>
            <th>Severity</th>
            <th>Status</th>
            <th>Reported</th>
          </tr>
        </thead>
        <tbody>
          ${tableRows || '<tr><td colspan="6" style="text-align:center;">No records match the filter.</td></tr>'}
        </tbody>
      </table>
    `;
    
    // Trigger print
    window.print();
  },

  renderRecommendations: function(recs) {
    const container = document.getElementById('advisor-recommendations');
    if (!container) return;
    
    if (!recs || recs.length === 0) {
      container.innerHTML = `<div style="font-size:0.85rem; color:var(--neutral-600); padding:12px; border: 1px dashed var(--neutral-300); border-radius:var(--radius); text-align:center;">🔍 No actionable clusters detected. Upkeep looks stable.</div>`;
      return;
    }
    
    let html = '';
    recs.forEach(r => {
      html += `
        <div style="padding:14px; background:var(--primary-light); color:var(--neutral-800); border-radius:var(--radius-sm); border:1px solid var(--primary-border); display:flex; flex-direction:column; gap:8px;">
          <div style="display:flex; justify-content:space-between; align-items:start;">
            <h4 style="font-size:0.95rem; font-weight:600; color:var(--primary-dark); margin: 0;">⚠️ ${r.title}</h4>
            <span class="badge-cat cat-${r.category}" style="font-size:0.7rem; padding:2px 6px;">${r.count} reports</span>
          </div>
          <p style="font-size:0.85rem; line-height:1.4; color:var(--neutral-700); margin: 4px 0 0 0;">${r.description}</p>
          <div style="display:flex; justify-content:space-between; align-items:center; margin-top:4px;">
            <span style="font-size:0.75rem; color:var(--neutral-500);">Target: [${r.lat.toFixed(4)}, ${r.lng.toFixed(4)}]</span>
            <button class="btn btn-secondary" style="padding:4px 8px; font-size:0.75rem;" onclick="CivicMap.init('auth-map', ${r.lat}, ${r.lng}, 16); CivicMap.addMarker(${r.lat}, ${r.lng}, 'Recommendation Center', true);">Locate on Map</button>
          </div>
        </div>
      `;
    });
    container.innerHTML = html;
  }
};
