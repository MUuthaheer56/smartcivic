/* SmartCivic - Offline Operations Caching */

const QUEUE_KEY = 'sc_offline_queue';

function getQueue() {
  return JSON.parse(localStorage.getItem(QUEUE_KEY) || '[]');
}

function saveQueue(q) {
  localStorage.setItem(QUEUE_KEY, JSON.stringify(q));
}

function queueReport(formData) {
  const q = getQueue();
  const entry = {
    id: Date.now(),
    title: formData.get('title'),
    description: formData.get('description'),
    category: formData.get('category'),
    lat: formData.get('lat'),
    lng: formData.get('lng'),
    address: formData.get('address'),
    queued_at: new Date().toISOString()
  };
  q.push(entry);
  saveQueue(q);
  showToast("You are offline. Your report was queued locally and will submit automatically when connection is restored.", 'warning');
}

async function flushQueue() {
  const q = getQueue();
  if (!q.length || !Auth.isLoggedIn()) return;
  
  const remaining = [];
  for (const entry of q) {
    const fd = new FormData();
    // Appends fields to FormData
    Object.entries(entry).forEach(([k, v]) => {
      if (k !== 'id' && k !== 'queued_at') {
        fd.append(k, v);
      }
    });
    
    // Attempt report API post
    const res = await apiFetch('/api/issues/report', {
      method: 'POST',
      body: fd
    });
    
    if (!res?.success) {
      remaining.push(entry);
    } else {
      showToast(`Offline report sync complete: "${entry.title}"`, 'success');
    }
  }
  saveQueue(remaining);
}

window.addEventListener('online', flushQueue);

document.addEventListener('DOMContentLoaded', () => {
  if (!navigator.onLine) {
    showToast("You are offline. Features may be limited. Report forms will cache submissions locally.", "warning");
  }
  flushQueue();
});
