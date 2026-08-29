/* SmartCivic - Field Worker Scripts */

const WorkerRoute = {
  activeRoute: null,
  watchId: null,

  init: async function() {
    await WorkerRoute.loadActiveRoute();
    WorkerRoute.startLocationTracking();
  },

  loadActiveRoute: async function() {
    const res = await apiFetch('/api/workers/my-route');
    const container = document.getElementById('active-route-container');
    if (!container) return;
    
    if (!res?.success || !res.data) {
      container.innerHTML = `
        <div class="card" style="text-align:center; padding:30px;">
          <h3 data-i18n="empty_no_route">No active route assigned.</h3>
          <p style="color:var(--neutral-600); margin-top:10px;">Please contact authority to assign a validation and fix path.</p>
        </div>
      `;
      if (typeof applyTranslations === 'function') applyTranslations();
      return;
    }
    
    const route = res.data;
    WorkerRoute.activeRoute = route;
    
    // Set values
    document.getElementById('route-distance').textContent = `${route.total_distance_km} km`;
    document.getElementById('route-duration').textContent = `${route.estimated_duration_min} mins`;
    
    let wpsHtml = '';
    route.waypoints.forEach(wp => {
      const isCompleted = wp.status === 'resolved';
      const isDepot = wp.issue_id === 'depot';
      
      let badgeHtml = '';
      if (isDepot) {
        badgeHtml = `<span style="background:var(--primary-light); color:var(--primary-dark); font-size:0.75rem; padding:2px 6px; border-radius:4px;">DEPOT</span>`;
      } else {
        badgeHtml = `<span style="padding:2px 6px; border-radius:4px; font-size:0.75rem;" class="status-badge">${wp.status.replace('_', ' ')}</span>`;
      }
      
      wpsHtml += `
        <div class="waypoint-item ${isCompleted ? 'completed' : ''}" style="margin-bottom:12px; position:relative;">
          <div class="waypoint-seq">${wp.sequence}</div>
          <div class="waypoint-header">
            <h4 class="waypoint-title">${isDepot ? 'Starting Depot' : wp.title}</h4>
            ${badgeHtml}
          </div>
          <div class="waypoint-body">
            <p>${isDepot ? 'Current GPS Location' : wp.address}</p>
            ${wp.sla_status && !isDepot ? `
              <div style="font-size:0.8rem; margin-top:6px; color:${wp.sla_status.is_overdue ? 'var(--danger)' : 'var(--neutral-600)'}">
                ⏰ SLA: ${wp.sla_status.days_remaining} days remaining
              </div>
            ` : ''}
          </div>
          
          ${!isDepot && !isCompleted ? `
            <div class="waypoint-actions" style="margin-top:10px;">
              <button class="btn btn-primary" style="padding:4px 10px; font-size:0.8rem;" onclick="WorkerRoute.markResolved('${wp.issue_id}')">Resolve Issue</button>
              <button class="btn btn-secondary" style="padding:4px 10px; font-size:0.8rem;" onclick="window.location.href='/issues/${wp.issue_id}'">View Details</button>
            </div>
          ` : ''}
        </div>
      `;
    });
    
    container.innerHTML = `
      <div style="margin-bottom:20px; display:flex; justify-content:space-between; font-weight:bold;">
        <span>Active Path Sequence</span>
        <button class="btn btn-secondary" style="padding:4px 10px; font-size:0.8rem;" onclick="WorkerRoute.loadActiveRoute()">Sync</button>
      </div>
      <div class="waypoint-list">
        ${wpsHtml}
      </div>
    `;
    
    // Load Leaflet markers
    if (typeof CivicMap !== 'undefined') {
      CivicMap.init('worker-map', route.waypoints[0].lat, route.waypoints[0].lng, 14);
      CivicMap.clearMarkers();
      route.waypoints.forEach(wp => {
        const popup = `<strong>Seq ${wp.sequence}:</strong> ${wp.title || 'Depot'}<br/>${wp.address || ''}`;
        CivicMap.addMarker(wp.lat, wp.lng, popup, wp.severity >= 4);
      });
      CivicMap.fitMarkers();
      CivicMap.drawRoutePath(route.waypoints);
    }
  },

  markResolved: async function(issueId) {
    const note = prompt("Please enter a resolution note:");
    if (note === null) return; // user cancelled
    
    const fileInput = document.createElement('input');
    fileInput.type = 'file';
    fileInput.accept = 'image/*';
    fileInput.style.display = 'none';
    document.body.appendChild(fileInput);
    
    fileInput.onchange = async () => {
      const file = fileInput.files[0];
      const fd = new FormData();
      fd.append('status', 'resolved');
      fd.append('note', note);
      if (file) {
        fd.append('resolution_image', file);
      }
      
      const res = await apiFetch(`/api/issues/${issueId}/status`, {
        method: 'PUT',
        body: fd
      });
      
      document.body.removeChild(fileInput);
      
      if (res?.success) {
        showToast("Issue resolved successfully!", "success");
        WorkerRoute.loadActiveRoute();
      } else if (res) {
        showToast(res.message, "error");
      }
    };
    
    // Prompt file select or proceed without image
    if (confirm("Would you like to upload a resolution photo?")) {
      fileInput.click();
    } else {
      document.body.removeChild(fileInput);
      
      // Submit without image
      const fd = new FormData();
      fd.append('status', 'resolved');
      fd.append('note', note);
      
      const res = await apiFetch(`/api/issues/${issueId}/status`, {
        method: 'PUT',
        body: fd
      });
      
      if (res?.success) {
        showToast("Issue resolved successfully!", "success");
        WorkerRoute.loadActiveRoute();
      } else if (res) {
        showToast(res.message, "error");
      }
    }
  },

  startLocationTracking: function() {
    if (navigator.geolocation) {
      // Send location update every 30 seconds
      WorkerRoute.updateGPS();
      WorkerRoute.watchId = setInterval(WorkerRoute.updateGPS, 30000);
    }
  },

  updateGPS: function() {
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        const lat = pos.coords.latitude;
        const lng = pos.coords.longitude;
        
        const res = await apiFetch('/api/workers/update-location', {
          method: 'PUT',
          body: JSON.stringify({ lat, lng })
        });
        
        if (res?.success) {
          console.log("GPS Location synced:", lat, lng);
          const tracker = document.getElementById('tracking-status');
          if (tracker) {
            tracker.textContent = `Live GPS Active (Lat: ${lat.toFixed(4)}, Lng: ${lng.toFixed(4)})`;
          }
        }
      },
      (err) => {
        console.warn("GPS Tracking error:", err);
      }
    );
  }
};
