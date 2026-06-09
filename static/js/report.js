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
