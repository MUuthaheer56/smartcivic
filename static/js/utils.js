// static/js/utils.js — SmartCivic Authentication & Global Utilities

// Global HTML Escaping to prevent Stored & Reflected XSS (FE-01, FE-02, FE-03, FE-04)
function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
window.escapeHtml = escapeHtml;

const SmartCivicAuth = {
  getToken() {
    // Web clients use HttpOnly cookies for security. Return null for web JS.
    return null;
  },

  getUser() {
    try {
      return JSON.parse(localStorage.getItem('sc_user') || 'null');
    } catch {
      return null;
    }
  },

  isLoggedIn() {
    // If user object is cached in localStorage, consider logged in on client side;
    // Server enforces actual authentication via HttpOnly JWT cookies.
    return !!this.getUser();
  },

  async logout() {
    try {
      await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' });
    } catch (e) {
      console.warn("Logout request failed:", e);
    }
    localStorage.removeItem('sc_user');
    window.location.href = '/login';
  },

  // Add Authorization & CSRF headers to every API call
  async fetch(url, options = {}) {
    const isFormData = typeof FormData !== 'undefined' && options.body instanceof FormData;
    const headers = { ...(options.headers || {}) };

    if (isFormData) {
      delete headers["Content-Type"];
      delete headers["content-type"];
    } else if (!headers["Content-Type"] && !headers["content-type"]) {
      headers["Content-Type"] = "application/json";
    }

    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;
    if (csrfToken && !headers["X-CSRFToken"]) {
      headers["X-CSRFToken"] = csrfToken;
    }

    const mergedOptions = {
      ...options,
      credentials: options.credentials || 'same-origin',
      headers
    };

    return fetch(url, mergedOptions);
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

window.SmartCivicAuth = SmartCivicAuth;
window.authFetch = SmartCivicAuth.fetch.bind(SmartCivicAuth);

// Intercept window.fetch for state-changing requests to supply CSRF token and send same-origin credentials
const _originalFetch = window.fetch;
window.fetch = function (url, options = {}) {
  const method = (options.method || 'GET').toUpperCase();
  const requiresCsrf = ['POST', 'PUT', 'DELETE', 'PATCH'].includes(method);
  const isSameOrigin = typeof url === 'string' && (url.startsWith('/') || url.startsWith(window.location.origin));

  if (requiresCsrf && isSameOrigin) {
    const headers = new Headers(options.headers || {});
    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;
    if (csrfToken && !headers.has('X-CSRFToken')) {
      headers.set('X-CSRFToken', csrfToken);
    }
    options = {
      ...options,
      credentials: options.credentials || 'same-origin',
      headers: headers
    };
  } else if (isSameOrigin && !options.credentials) {
    options = {
      ...options,
      credentials: 'same-origin'
    };
  }
  return _originalFetch.call(this, url, options);
};
