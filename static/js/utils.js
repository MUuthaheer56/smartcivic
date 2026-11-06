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

/**
 * Shared api() helper for all data fetches (UI-REPAIR requirement 4)
 * - Sends CSRF header
 * - Includes credentials
 * - Handles 401 by redirecting to login
 * - Handles 429 with a friendly retry message
 * - Throws on non-OK
 * - Has an 8-second timeout
 */
async function api(url, options = {}) {
  const timeoutMs = options.timeoutMs || 8000;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  const method = (options.method || 'GET').toUpperCase();
  const headers = { ...(options.headers || {}) };

  const isFormData = typeof FormData !== 'undefined' && options.body instanceof FormData;
  if (!isFormData && !headers['Content-Type'] && !headers['content-type'] && ['POST', 'PUT', 'PATCH'].includes(method)) {
    headers['Content-Type'] = 'application/json';
  }

  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;
  if (csrfToken && !headers['X-CSRFToken']) {
    headers['X-CSRFToken'] = csrfToken;
  }

  const fetchOptions = {
    ...options,
    method,
    headers,
    credentials: options.credentials || 'same-origin',
    signal: options.signal || controller.signal
  };

  try {
    const response = await _originalFetch(url, fetchOptions);
    clearTimeout(timeoutId);

    if (response.status === 401) {
      console.warn('[api] 401 Unauthorized for', url, '— redirecting to /login');
      if (window.location.pathname !== '/login') {
        window.location.href = '/login?next=' + encodeURIComponent(window.location.pathname + window.location.search);
      }
      const err = new Error('Session expired or unauthorized. Redirecting to login...');
      err.status = 401;
      throw err;
    }

    if (response.status === 429) {
      const retryMsg = 'Too many requests. Please wait a moment and try again.';
      console.warn('[api] 429 Rate limited for', url);
      const toastEl = document.getElementById('rateLimitToast') || createRateLimitToast(retryMsg);
      if (toastEl) {
        toastEl.textContent = retryMsg;
        toastEl.style.display = 'block';
        setTimeout(() => { if (toastEl) toastEl.style.display = 'none'; }, 4000);
      }
      const err = new Error(retryMsg);
      err.status = 429;
      throw err;
    }

    if (!response.ok) {
      let errPayload = null;
      try {
        errPayload = await response.clone().json();
      } catch (e) {
        // Not JSON
      }
      const errMsg = (errPayload && (errPayload.message || (errPayload.error && errPayload.error.message))) ||
                     `Request failed with status ${response.status}`;
      const err = new Error(errMsg);
      err.status = response.status;
      err.data = errPayload;
      throw err;
    }

    const contentType = response.headers.get('content-type') || '';
    let result;
    if (contentType.includes('application/json')) {
      result = await response.json();
    } else {
      result = await response.text();
    }

    // Attach backwards-compatible properties if result is an object
    if (result && typeof result === 'object') {
      if (!('json' in result)) {
        Object.defineProperty(result, 'json', {
          value: async () => result,
          configurable: true,
          writable: true
        });
      }
      if (!('ok' in result)) {
        Object.defineProperty(result, 'ok', {
          value: true,
          configurable: true,
          writable: true
        });
      }
      if (!('status' in result)) {
        Object.defineProperty(result, 'status', {
          value: response.status,
          configurable: true,
          writable: true
        });
      }
    }

    return result;
  } catch (err) {
    clearTimeout(timeoutId);
    if (err.name === 'AbortError') {
      const timeoutErr = new Error(`Request timed out after ${timeoutMs / 1000}s`);
      timeoutErr.status = 408;
      throw timeoutErr;
    }
    throw err;
  }
}

function createRateLimitToast(msg) {
  const el = document.createElement('div');
  el.id = 'rateLimitToast';
  el.style.cssText = 'position:fixed;bottom:24px;right:24px;background:#ef4444;color:#fff;padding:12px 20px;border-radius:8px;font-weight:600;z-index:99999;box-shadow:0 4px 12px rgba(0,0,0,0.3);';
  el.textContent = msg;
  document.body.appendChild(el);
  return el;
}

/**
 * Renders a spinner inside container
 */
function renderLoading(container, message = 'Loading...') {
  if (typeof container === 'string') container = document.getElementById(container);
  if (!container) return;
  container.innerHTML = `
    <div class="loading-state" style="padding: 2.5rem; text-align: center; color: var(--text-muted, #94a3b8);">
      <i class="fa-solid fa-spinner fa-spin" style="font-size: 1.8rem; margin-bottom: 0.75rem; color: var(--primary, #3b82f6);"></i>
      <div style="font-size: 0.95rem;">${escapeHtml(message)}</div>
    </div>
  `;
}

/**
 * Renders an error message with a retry button inside container
 */
function renderErrorRetry(container, message = 'Unable to load data.', retryFn) {
  if (typeof container === 'string') container = document.getElementById(container);
  if (!container) return;
  container.innerHTML = `
    <div class="error-retry-state" style="padding: 2.5rem; text-align: center; color: var(--text-muted, #94a3b8);">
      <i class="fa-solid fa-triangle-exclamation" style="font-size: 2rem; color: #ef4444; margin-bottom: 0.75rem;"></i>
      <div style="font-size: 0.95rem; margin-bottom: 1rem; color: var(--text-main, #f8fafc);">${escapeHtml(message)}</div>
      <button type="button" class="btn btn-secondary btn-retry" style="padding: 0.5rem 1.25rem; font-size: 0.85rem; border-radius: 6px; cursor: pointer;">
        <i class="fa-solid fa-rotate-right" style="margin-right: 0.5rem;"></i> Retry
      </button>
    </div>
  `;
  if (typeof retryFn === 'function') {
    const btn = container.querySelector('.btn-retry');
    if (btn) btn.addEventListener('click', () => {
      renderLoading(container);
      retryFn();
    });
  }
}

window.api = api;
window.renderLoading = renderLoading;
window.renderErrorRetry = renderErrorRetry;
