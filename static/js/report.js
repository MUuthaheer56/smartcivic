/* SmartCivic - Issue Report Helper */

document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('report-form');
  if (!form) return;
  
  const titleInput = document.getElementById('title');
  const categorySelect = document.getElementById('category');
  const detectLocBtn = document.getElementById('detect-location-btn');
  const latInput = document.getElementById('lat');
  const lngInput = document.getElementById('lng');
  const addressInput = document.getElementById('address');
  
  // Category suggestion
  if (titleInput && categorySelect) {
    titleInput.addEventListener('input', debounce(async (e) => {
      const title = e.target.value;
      if (title.length < 3) return;
      
      const res = await apiFetch(`/api/issues/suggest-category?title=${encodeURIComponent(title)}`);
      if (res?.success && res.data?.suggested_category !== 'other') {
        categorySelect.value = res.data.suggested_category;
        showCategorySuggestionToast(res.data.suggested_category);
      }
    }, 500));
  }
  
  // Geolocation detection
  if (detectLocBtn) {
    detectLocBtn.addEventListener('click', () => {
      detectLocBtn.disabled = true;
      detectLocBtn.textContent = "Detecting...";
      
      if (navigator.geolocation) {
        navigator.geolocation.getCurrentPosition(
          (position) => {
            const lat = position.coords.latitude;
            const lng = position.coords.longitude;
            
            latInput.value = lat;
            lngInput.value = lng;
            
            showToast("Location detected successfully!", "success");
            detectLocBtn.disabled = false;
            detectLocBtn.textContent = "Detect Location";
            
            // Auto-fill mock address or map marker if needed
            if (typeof CivicMap !== 'undefined') {
              CivicMap.init('report-map', lat, lng, 15);
              CivicMap.setReportMarker(lat, lng, "Report Location");
            }
          },
          (error) => {
            console.error(error);
            showToast("Failed to detect location. Please set coordinates manually.", "error");
            detectLocBtn.disabled = false;
            detectLocBtn.textContent = "Detect Location";
          }
        );
      } else {
        showToast("Geolocation is not supported by your browser.", "error");
        detectLocBtn.disabled = false;
        detectLocBtn.textContent = "Detect Location";
      }
    });
  }
  
  // Submit Issue
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const formData = new FormData(form);
    
    // Check if offline
    if (!navigator.onLine) {
      if (typeof queueReport === 'function') {
        queueReport(formData);
        form.reset();
        return;
      }
    }
    
    const res = await apiFetch('/api/issues/report', {
      method: 'POST',
      body: formData
    });
    
    if (res?.success) {
      // Check if duplicate alert
      if (res.data?.nearby_duplicate) {
        const dup = res.data.nearby_duplicate;
        if (confirm(`A similar issue "${dup.title}" was already reported nearby. Do you still want to report this issue?`)) {
          formData.append('bypass_duplicate', 'true');
          const bypassRes = await apiFetch('/api/issues/report', {
            method: 'POST',
            body: formData
          });
          if (bypassRes?.success) {
            showToast("Issue reported successfully!", "success");
            window.location.href = '/issues';
          }
        }
      } else {
        showToast("Issue reported successfully!", "success");
        window.location.href = '/issues';
      }
    } else if (res) {
      showToast(res.message, "error");
    }
  });
});

function debounce(func, wait) {
  let timeout;
  return function executedFunction(...args) {
    const later = () => {
      clearTimeout(timeout);
      func(...args);
    };
    clearTimeout(timeout);
    timeout = setTimeout(later, wait);
  };
}

function showCategorySuggestionToast(category) {
  const pretty = {
    water: "Water Supply/Leakage",
    pothole: "Pothole/Road Damage",
    garbage: "Garbage Dump/Trash",
    streetlight: "Streetlight Malfunction",
    sewage: "Sewage Overflow",
    noise: "Noise Pollution"
  }[category] || category;
  
  showToast(`Auto-suggested category: ${pretty}`, "info", 3000);
}

const NoiseRecorder = {
  stream: null,
  context: null,
  analyser: null,
  animFrame: null,
  peakDb: -Infinity,

  start: async function() {
    try {
      NoiseRecorder.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      NoiseRecorder.context = new (window.AudioContext || window.webkitAudioContext)();
      const source = NoiseRecorder.context.createMediaStreamSource(NoiseRecorder.stream);
      NoiseRecorder.analyser = NoiseRecorder.context.createAnalyser();
      NoiseRecorder.analyser.fftSize = 2048;
      source.connect(NoiseRecorder.analyser);
      
      document.getElementById('start-recording-btn').style.display = 'none';
      document.getElementById('stop-recording-btn').style.display = 'inline-flex';
      
      NoiseRecorder._tick();
    } catch (e) {
      showToast('Microphone access denied. Please allow microphone access.', 'error');
    }
  },

  _tick: function() {
    const buf = new Float32Array(NoiseRecorder.analyser.fftSize);
    NoiseRecorder.analyser.getFloatTimeDomainData(buf);
    const rms = Math.sqrt(buf.reduce((s, v) => s + v * v, 0) / buf.length);
    const refPressure = 20e-6; // 20 μPa reference
    const dbSpl = rms > 0 ? 20 * Math.log10(rms / refPressure) : 0;
    const dbDisplay = Math.max(0, Math.min(150, dbSpl));
    
    if (dbDisplay > NoiseRecorder.peakDb) NoiseRecorder.peakDb = dbDisplay;
    
    const display = document.getElementById('db-live-display');
    if (display) {
      display.textContent = `${dbDisplay.toFixed(1)} dB`;
      display.style.color = dbDisplay > 65 ? 'var(--sc-danger)' : dbDisplay > 55 ? 'var(--sc-warning)' : 'var(--sc-success)';
    }
    
    NoiseRecorder.animFrame = requestAnimationFrame(NoiseRecorder._tick);
  },

  stop: async function() {
    cancelAnimationFrame(NoiseRecorder.animFrame);
    if (NoiseRecorder.stream) NoiseRecorder.stream.getTracks().forEach(t => t.stop());
    if (NoiseRecorder.context) await NoiseRecorder.context.close();
    
    document.getElementById('start-recording-btn').style.display = 'inline-flex';
    document.getElementById('stop-recording-btn').style.display = 'none';
    
    const peakDb = Math.max(0, Math.min(150, NoiseRecorder.peakDb));
    document.getElementById('recorded-db-spl').value = peakDb.toFixed(1);
    
    // Validate against CPCB
    const zoneSelect = document.getElementById('noise-zone-type');
    const zone = zoneSelect ? zoneSelect.value : 'residential';
    const hour = new Date().getHours();
    const isNight = hour >= 22 || hour < 6;
    
    const res = await apiFetch('/api/ai/validate-noise', {
      method: 'POST',
      body: JSON.stringify({ db_spl: peakDb, zone_type: zone, is_night: isNight })
    });
    
    const resultDiv = document.getElementById('noise-cpcb-result');
    if (res?.success) {
      const d = res.data;
      document.getElementById('noise-cpcb-status').value = d.cpcb_status;
      const color = d.compliant ? 'var(--sc-success)' : 'var(--sc-danger)';
      resultDiv.innerHTML = `
        <div style="padding:10px 12px;border-left:4px solid ${color};background:${d.compliant ? 'var(--sc-success-soft)' : 'var(--sc-danger-soft)'};border-radius:0 8px 8px 0;font-size:0.85rem;">
          <strong style="color:${color};">${d.cpcb_status}</strong> — 
          Peak ${peakDb.toFixed(1)} dB (Limit: ${d.limit_db} dB ${d.zone} ${d.period}) — 
          Suggested Severity: ${'★'.repeat(d.estimated_severity)}${'☆'.repeat(5-d.estimated_severity)}
        </div>
      `;
    }
    
    NoiseRecorder.peakDb = -Infinity;
  }
};

// Show noise recorder only when category = noise
document.addEventListener('DOMContentLoaded', () => {
  const catSelect = document.getElementById('category');
  if (catSelect) {
    // Initial check
    const section = document.getElementById('noise-recorder-section');
    if (section) section.style.display = catSelect.value === 'noise' ? 'block' : 'none';

    catSelect.addEventListener('change', () => {
      if (section) section.style.display = catSelect.value === 'noise' ? 'block' : 'none';
    });
  }
});
