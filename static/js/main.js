/* SmartCivic - Global main.js Utilities */

const Auth = {
  getToken: () => localStorage.getItem('sc_token'),
  getUser: () => JSON.parse(localStorage.getItem('sc_user') || 'null'),
  setSession: (token, user) => {  
    localStorage.setItem('sc_token', token);
    localStorage.setItem('sc_user', JSON.stringify(user));
  },
  clearSession: () => {
    localStorage.removeItem('sc_token');
    localStorage.removeItem('sc_user');
  },
  isLoggedIn: () => !!localStorage.getItem('sc_token')
};

async function apiFetch(url, options = {}) {
  const token = Auth.getToken();
  const headers = {
    ...(!(options.body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}),
    ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
    ...(options.headers || {})
  };
  
  try {
    const res = await fetch(url, { ...options, headers });
    if (res.status === 401) {
      Auth.clearSession();
      if (!url.includes('/api/auth/login')) {
        window.location.href = '/login';
        return null;
      }
    }
    return await res.json();
  } catch (e) {
    if (typeof t === 'function') {
      showToast(t('toast_error_network'), 'error');
    } else {
      showToast("Network error. Please try again.", 'error');
    }
    throw e;
  }
}

function showToast(message, type = 'info', duration = 4000) {
  let container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    container.className = 'toast-container';
    document.body.appendChild(container);
  }
  
  const icon = { success: '✓', error: '✗', warning: '⚠', info: 'ℹ' }[type] || '';
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `
    <span class="toast-icon">${icon}</span>
    <span class="toast-msg">${message}</span>
    <button class="toast-close" onclick="this.parentElement.remove()">×</button>
  `;
  
  container.appendChild(toast);
  toast.style.animation = 'slideIn 0.3s ease';
  
  setTimeout(() => {
    toast.style.animation = 'slideOut 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, duration);
}

function timeAgo(isoString) {
  if (!isoString) return '';
  const diff = Date.now() - new Date(isoString).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  if (mins < 1440) return `${Math.floor(mins / 60)}h ago`;
  return `${Math.floor(mins / 1440)}d ago`;
}

function severityStars(n) {
  return '★'.repeat(n) + '☆'.repeat(5 - n);
}

function getSLAClass(sla) {
  if (!sla) return '';
  if (sla.is_overdue) return 'sla-overdue';
  if (sla.days_remaining <= 1) return 'sla-warning';
  return 'sla-ok';
}

function initNavbar() {
  const user = Auth.getUser();
  const authNav = document.getElementById('auth-nav');
  if (!authNav) return;
  
  if (user) {
    const tierClass = `tier-${user.reputation_tier?.toLowerCase().replace(' ', '-') || 'newcomer'}`;
    const reputation_score = user.reputation_score || 0;
    const reputation_tier = user.reputation_tier || 'Newcomer';
    
    let dashboardLink = '';
    if (user.role === 'authority') {
      dashboardLink = `<a href="/authority" data-i18n="nav_dashboard" class="btn btn-secondary">Dashboard</a>
  <a href="/ai-insights" class="btn btn-secondary" style="background:var(--sc-gradient-brand);color:white;border:none;">🧠 AI Hub</a>`;
    } else if (user.role === 'resident') {
      dashboardLink = `<a href="/community" data-i18n="nav_community" class="btn btn-secondary">Community</a>`;
    } else if (user.role === 'field_worker') {
      dashboardLink = `<a href="/worker" class="btn btn-secondary">My Route</a>`;
    }
    
    authNav.innerHTML = `
      <span class="reputation-badge ${tierClass}">${reputation_tier} · ${reputation_score}pts</span>
      ${dashboardLink}
      ${user.role === 'field_worker' ? '<a href="/worker/stats" class="btn btn-secondary">My Stats</a>' : ''}
      <a href="/my-issues" class="btn btn-secondary">My Issues</a>
      <button id="notif-bell" class="btn btn-secondary" onclick="window.location.href='/my-issues#notifications'" style="position: relative;">
        🔔 <span id="notif-count" class="badge hidden" style="position: absolute; top: -5px; right: -5px; background: red; color: white; border-radius: 50%; padding: 2px 6px; font-size: 0.6rem;">0</span>
      </button>
      <button onclick="toggleTheme()" class="theme-btn">🌙</button>
      <button onclick="logout()" class="btn btn-secondary" data-i18n="nav_logout">Logout</button>
    `;
    
  } else {
    authNav.innerHTML = `
      <button onclick="toggleTheme()" class="theme-btn">🌙</button>
      <a href="/login" class="btn btn-secondary" data-i18n="nav_login">Login</a>
      <a href="/register" class="btn btn-primary" data-i18n="nav_register">Register</a>
    `;
  }
}

function logout() {
  Auth.clearSession();
  window.location.href = '/login';
}

// Socket.IO
let socket;
function initSocket() {
  const user = Auth.getUser();
  if (!user || typeof io === 'undefined') return;
  
  socket = io('/civic');
  
  socket.on('connect', () => {
    socket.emit('join_room', { room: `community_${user.community_id}` });
    socket.emit('join_room', { room: `user_${user.user_id}` });
    if (user.role === 'authority') {
      socket.emit('join_room', { room: `authority_${user.community_id}` });
    }
    if (user.role === 'field_worker') {
      socket.emit('join_room', { room: `worker_${user.user_id}` });
    }
  });
  
  socket.on('notification', d => {
    showToast(d.message, 'info');
    loadNotifCount();
  });
  
  socket.on('new_issue', d => {
    showToast(`New issue reported: ${d.title}`, 'warning');
  });
  
  socket.on('issue_validated', d => {
    showToast(`✓ Issue Validated: "${d.title}"`, 'success');
  });
  
  socket.on('urgent_issue', d => {
    showToast(`🚨 URGENT: "${d.title}" (Severity ${d.severity})`, 'error', 10000);
    const banner = document.getElementById('urgent-banner');
    if (banner) {
      banner.textContent = `🚨 Urgent: ${d.title}`;
      banner.style.display = 'block';
    }
  });
  
  socket.on('route_assigned', d => {
    showToast('New service route assigned!', 'success');
    setTimeout(() => {
      window.location.href = '/worker';
    }, 2000);
  });
  
  socket.on('route_cancelled', d => {
    showToast('Active route unassigned by authority.', 'warning');
    if (window.location.pathname === '/worker') {
      setTimeout(() => {
        window.location.reload();
      }, 2000);
    }
  });
  
  socket.on('sla_breach', d => {
    if (user.role === 'authority') {
      showToast(`⏰ SLA breached: "${d.title}"`, 'error', 8000);
    }
  });
  
  socket.on('new_announcement', d => {
    showToast(`📢 ${d.title}: ${d.body}`, 'info', 8000);
  });
}

async function loadNotifCount() {
  if (!Auth.isLoggedIn()) return;
  const res = await apiFetch('/api/notifications/');
  if (res?.success) {
    const unread = (res.data || []).filter(n => !n.is_read).length;
    const badge = document.getElementById('notif-count');
    if (badge) {
      badge.textContent = unread;
      badge.classList.toggle('hidden', unread === 0);
    }
  }
}


function toggleTheme() {
  const html = document.documentElement;
  const isDark = html.getAttribute('data-theme') === 'dark';
  html.setAttribute('data-theme', isDark ? 'light' : 'dark');
  localStorage.setItem('sc_theme', isDark ? 'light' : 'dark');
}

function initTheme() {
  const saved = localStorage.getItem('sc_theme') || 'light';
  document.documentElement.setAttribute('data-theme', saved);
}

document.addEventListener('DOMContentLoaded', () => {
  initTheme();
  initNavbar();
  initSocket();
});

function toggleMobileNav() {
  const nl = document.getElementById('nav-links');
  if (nl) nl.classList.toggle('open');
}
