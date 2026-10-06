// static/js/utils.js — SmartCivic Authentication & Global Utilities

const SmartCivicAuth = {
  getToken() {
    return sessionStorage.getItem('sc_access_token') || localStorage.getItem('sc_access_token');
  },

  getUser() {
    try {
      return JSON.parse(localStorage.getItem('sc_user') || 'null');
    } catch {
      return null;
    }
  },

  isLoggedIn() {
    return !!this.getToken();
  },

  logout() {
    sessionStorage.removeItem('sc_access_token');
    localStorage.removeItem('sc_refresh_token');
    localStorage.removeItem('sc_user');
    window.location.href = '/login';
  },

  // Add Authorization & CSRF headers to every API call
  async fetch(url, options = {}) {
    const token = this.getToken();
    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;
    const headers = {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
      ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
      ...(csrfToken ? { 'X-CSRFToken': csrfToken } : {}),
    };
    return fetch(url, { ...options, headers });
  },


  // Redirect to login if not authenticated
  requireAuth() {
    if (!this.isLoggedIn()) {
      window.location.href = '/login?next=' + encodeURIComponent(window.location.pathname);
      return false;
    }
    return true;
  },

  // Redirect to ward verification if citizen is unverified
  requireVerified() {
    const user = this.getUser();
    if (user && (user.role === 'citizen' || user.role === 'resident') && !user.verified) {
      window.location.href = '/citizen/verify-ward';
      return false;
    }
    return true;
  }
};

// Make available globally
window.SmartCivicAuth = SmartCivicAuth;
