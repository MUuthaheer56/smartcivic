/**
 * static/js/location.js — SmartCivic Live Location & Map Engine
 */

'use strict';

const SmartCivicMap = (function () {
  let _map         = null;
  let _marker      = null;
  let _initialized = false;

  const DEFAULT_LAT  = 12.9716;
  const DEFAULT_LNG  = 77.5946;
  const DEFAULT_ZOOM = 13;

  /**
   * Initialize the map inside the given div ID.
   */
  function init(divId = 'sc-map', options = {}) {
    if (_initialized && _map) return;

    const container = document.getElementById(divId);
    if (!container) {
      console.warn('[SmartCivicMap] Container #' + divId + ' not found.');
      return;
    }

    if (container.offsetHeight === 0) {
      container.style.height = '300px';
    }

    if (typeof L === 'undefined') {
      console.warn('[SmartCivicMap] Leaflet JS library not loaded.');
      return;
    }

    _map = L.map(divId).setView([DEFAULT_LAT, DEFAULT_LNG], DEFAULT_ZOOM);

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      maxZoom: 19,
    }).addTo(_map);

    _map.on('click', function (e) {
      _placePin(e.latlng.lat, e.latlng.lng, options.onLocationSet);
    });

    _initialized = true;
  }

  /**
   * Place or move the location pin.
   */
  function _placePin(lat, lng, callback) {
    if (!_map) return;

    if (_marker) {
      _marker.setLatLng([lat, lng]);
    } else {
      _marker = L.marker([lat, lng], { draggable: true }).addTo(_map);

      _marker.on('dragend', function () {
        const pos = _marker.getLatLng();
        _updateHiddenFields(pos.lat, pos.lng);
        if (typeof callback === 'function') {
          callback({ lat: pos.lat, lng: pos.lng });
        }
      });
    }

    _map.panTo([lat, lng]);
    _updateHiddenFields(lat, lng);

    if (typeof callback === 'function') {
      callback({ lat, lng });
    }
  }

  /**
   * Write lat/lng into hidden form fields.
   */
  function _updateHiddenFields(lat, lng) {
    const latField = document.getElementById('latitude');
    const lngField = document.getElementById('longitude');
    if (latField) latField.value = lat.toFixed(6);
    if (lngField) lngField.value = lng.toFixed(6);
  }

  const DEFAULT_CENTER = { lat: DEFAULT_LAT, lng: DEFAULT_LNG };

  function _showLocationFallbackBanner(msg) {
    let banner = document.getElementById('location-fallback-banner');
    if (!banner) {
      banner = document.createElement('div');
      banner.id = 'location-fallback-banner';
      banner.className = 'alert alert-warning small my-2 py-2 px-3';
      banner.style.borderRadius = '6px';
      const container = document.getElementById('sc-map') || document.getElementById('location-status')?.parentNode;
      if (container && container.parentNode) {
        container.parentNode.insertBefore(banner, container);
      }
    }
    if (banner) {
      banner.textContent = msg;
      banner.style.display = 'block';
    }
  }

  function getLocation() {
    return new Promise((resolve) => {
      if (!navigator.geolocation || !window.isSecureContext) {
        const msg = "Couldn't detect location due to insecure connection or unsupported browser. Drag the pin to set location.";
        _showLocationFallbackBanner(msg);
        return resolve({ ...DEFAULT_CENTER, fallback: true, reason: "insecure_or_unsupported" });
      }
      navigator.geolocation.getCurrentPosition(
        (p) => resolve({ lat: p.coords.latitude, lng: p.coords.longitude, fallback: false }),
        (err) => {
          const msg = "Couldn't detect location. Drag the pin to set it.";
          _showLocationFallbackBanner(msg);
          resolve({ ...DEFAULT_CENTER, fallback: true, reason: err.code });
        },
        { enableHighAccuracy: true, timeout: 8000, maximumAge: 60000 }
      );
    });
  }

  /**
   * Request browser geolocation and fly to it.
   */
  function detectLocation(options = {}) {
    const statusEl = document.getElementById('location-status');

    function setStatus(msg, isError = false) {
      if (statusEl) {
        statusEl.textContent = msg;
        statusEl.className = isError ? 'text-danger small ms-2' : 'text-muted small ms-2';
      }
    }

    if (!navigator.geolocation || !window.isSecureContext) {
      const msg = 'Location detection not supported or insecure context (HTTPS required). Click on the map or drag pin.';
      setStatus(msg, true);
      _showLocationFallbackBanner("Couldn't detect location. Drag the pin to set it.");
      if (typeof options.onError === 'function') options.onError(msg);
      if (!_initialized) init('sc-map');
      _placePin(DEFAULT_LAT, DEFAULT_LNG, options.onLocationSet);
      return;
    }

    setStatus('Detecting location…');

    navigator.geolocation.getCurrentPosition(
      function (position) {
        const lat = position.coords.latitude;
        const lng = position.coords.longitude;
        const accuracy = Math.round(position.coords.accuracy);

        setStatus(`Location detected (±${accuracy}m)`);

        if (!_initialized) {
          init('sc-map');
        }

        if (_map) {
          _map.flyTo([lat, lng], 16);
          _placePin(lat, lng, options.onLocationSet);
        } else {
          _updateHiddenFields(lat, lng);
        }

        if (typeof options.onSuccess === 'function') {
          options.onSuccess({ lat, lng, accuracy });
        }
      },
      function (err) {
        let msg = 'Location error. Click on the map to pin your location.';
        switch (err.code) {
          case err.PERMISSION_DENIED:
            msg = 'Location access denied. Click on the map to pin your location.';
            break;
          case err.POSITION_UNAVAILABLE:
            msg = 'Location unavailable. Click on the map or type the address.';
            break;
          case err.TIMEOUT:
            msg = 'Location request timed out. Click on the map to pin your location.';
            break;
        }
        setStatus(msg, true);
        _showLocationFallbackBanner(msg);
        if (!_initialized) init('sc-map');
        _placePin(DEFAULT_LAT, DEFAULT_LNG, options.onLocationSet);
        if (typeof options.onError === 'function') options.onError(msg);
      },
      {
        enableHighAccuracy: true,
        timeout: 8000,
        maximumAge: 60000,
      }
    );
  }

  function getSelectedLocation() {
    const lat = document.getElementById('latitude')?.value;
    const lng = document.getElementById('longitude')?.value;
    if (!lat || !lng) return null;
    return { lat: parseFloat(lat), lng: parseFloat(lng) };
  }

  function invalidateSize() {
    if (_map) _map.invalidateSize();
  }

  return { init, detectLocation, getLocation, getSelectedLocation, invalidateSize };
})();


window.SmartCivicMap = SmartCivicMap;

/**
 * Reverse geocode lat/lng to a human-readable address.
 */
async function reverseGeocode(lat, lng) {
  try {
    const res = await fetch(
      `https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lng}`,
      { headers: { 'Accept-Language': 'en' } }
    );
    const data = await res.json();
    if (data && data.display_name) {
      const locField = document.getElementById('location-text');
      if (locField && !locField.value) {
        const a = data.address || {};
        const short = [a.road, a.suburb, a.city || a.town || a.village].filter(Boolean).join(', ');
        locField.value = short || data.display_name;
      }
    }
  } catch {
    // Non-fatal
  }
}

document.addEventListener('DOMContentLoaded', function () {
  const mapContainer = document.getElementById('sc-map');
  if (mapContainer) {
    SmartCivicMap.init('sc-map', {
      onLocationSet: function ({ lat, lng }) {
        reverseGeocode(lat, lng);
      }
    });
  }

  const detectBtn = document.getElementById('detect-location-btn');
  if (detectBtn) {
    detectBtn.addEventListener('click', function () {
      SmartCivicMap.detectLocation({
        onLocationSet: function ({ lat, lng }) {
          reverseGeocode(lat, lng);
        }
      });
    });
  }

  document.querySelectorAll('[data-bs-toggle="tab"]').forEach(function (tab) {
    tab.addEventListener('shown.bs.tab', function () {
      SmartCivicMap.invalidateSize();
    });
  });
});
