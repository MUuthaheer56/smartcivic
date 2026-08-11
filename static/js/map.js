/* SmartCivic - Map Utility */

const CivicMap = {
  map: null,
  markers: [],
  polyline: null,
  reportMarker: null,

  init: function(containerId, centerLat, centerLng, zoom = 13) {
    const container = document.getElementById(containerId);
    if (!container) return;
    
    // Check if Leaflet is loaded
    if (typeof L !== 'undefined') {
      try {
        if (CivicMap.map) {
          CivicMap.map.remove();
        }
        CivicMap.map = L.map(containerId).setView([centerLat, centerLng], zoom);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
          attribution: '&copy; OpenStreetMap contributors'
        }).addTo(CivicMap.map);
        
        // Fix for sizing issues in flex containers
        setTimeout(() => {
          CivicMap.map.invalidateSize();
        }, 300);
      } catch (e) {
        console.error("Leaflet init error:", e);
        CivicMap.initMockMap(container, centerLat, centerLng);
      }
    } else {
      CivicMap.initMockMap(container, centerLat, centerLng);
    }
  },

  initMockMap: function(container, lat, lng) {
    container.innerHTML = `
      <div class="map-placeholder" style="display:flex; flex-direction:column; gap:10px;">
        <div>🗺️ Map view center: [${parseFloat(lat).toFixed(4)}, ${parseFloat(lng).toFixed(4)}]</div>
        <div style="font-size:0.8rem; color:var(--neutral-600)">OpenStreetMap layer mock</div>
      </div>
    `;
  },

  addMarker: function(lat, lng, popupHtml, isUrgent = false) {
    if (typeof L !== 'undefined' && CivicMap.map) {
      const markerOptions = {};
      if (isUrgent) {
        // Red icon for urgent issues
        const redIcon = new L.Icon({
          iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-red.png',
          shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/0.7.7/images/marker-shadow.png',
          iconSize: [25, 41],
          iconAnchor: [12, 41],
          popupAnchor: [1, -34],
          shadowSize: [41, 41]
        });
        markerOptions.icon = redIcon;
      }
      
      const marker = L.marker([lat, lng], markerOptions).addTo(CivicMap.map);
      if (popupHtml) {
        marker.bindPopup(popupHtml);
      }
      CivicMap.markers.push(marker);
      return marker;
    } else {
      console.log(`Mock Marker at [${lat}, ${lng}]: ${popupHtml}`);
    }
  },

  clearMarkers: function() {
    if (typeof L !== 'undefined' && CivicMap.map) {
      CivicMap.markers.forEach(marker => {
        CivicMap.map.removeLayer(marker);
      });
      CivicMap.markers = [];
      if (CivicMap.polyline) {
        CivicMap.polyline.remove();
        CivicMap.polyline = null;
      }
      CivicMap.clearReportMarker();
    }
  },

  drawRoutePath: async function(waypoints) {
    if (typeof L !== 'undefined' && CivicMap.map && waypoints && waypoints.length > 1) {
      if (CivicMap.polyline) {
        CivicMap.polyline.remove();
        CivicMap.polyline = null;
      }
      
      try {
        const coordinates = waypoints
          .map(wp => `${wp.lng},${wp.lat}`)
          .join(';');
          
        const url = `https://router.project-osrm.org/route/v1/driving/${coordinates}?overview=full&geometries=geojson`;
        
        const response = await fetch(url);
        const data = await response.json();
        
        if (data.code === 'Ok' && data.routes && data.routes.length > 0) {
          const routeCoordinates = data.routes[0].geometry.coordinates;
          const leafletCoordinates = routeCoordinates.map(([lng, lat]) => [lat, lng]);
          
          CivicMap.polyline = L.polyline(leafletCoordinates, {
            color: '#2563eb',
            weight: 5,
            opacity: 0.8,
            dashArray: '8, 8',
            lineCap: 'round',
            lineJoin: 'round'
          }).addTo(CivicMap.map);
          return;
        }
      } catch (e) {
        console.error("OSRM routing failed, falling back to straight lines:", e);
      }
      
      // Fallback to straight lines
      const latlngs = waypoints.map(wp => [wp.lat, wp.lng]);
      CivicMap.polyline = L.polyline(latlngs, {
        color: '#2563eb',
        weight: 5,
        opacity: 0.8,
        dashArray: '8, 8',
        lineCap: 'round',
        lineJoin: 'round'
      }).addTo(CivicMap.map);
    }
  },

  fitMarkers: function() {
    if (typeof L !== 'undefined' && CivicMap.map && CivicMap.markers.length > 0) {
      const group = new L.featureGroup(CivicMap.markers);
      CivicMap.map.fitBounds(group.getBounds().pad(0.1));
    }
  },

  setReportMarker: function(lat, lng, popupHtml) {
    if (typeof L !== 'undefined' && CivicMap.map) {
      if (CivicMap.reportMarker) {
        CivicMap.map.removeLayer(CivicMap.reportMarker);
      }
      CivicMap.reportMarker = L.marker([lat, lng]).addTo(CivicMap.map);
      if (popupHtml) {
        CivicMap.reportMarker.bindPopup(popupHtml);
      }
      return CivicMap.reportMarker;
    }
  },

  clearReportMarker: function() {
    if (CivicMap.reportMarker && CivicMap.map) {
      CivicMap.map.removeLayer(CivicMap.reportMarker);
      CivicMap.reportMarker = null;
    }
  }
};
