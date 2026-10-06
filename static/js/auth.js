// static/js/auth.js — Login Form Handler & Role Redirects

document.addEventListener('DOMContentLoaded', function () {
  const loginForm = document.getElementById('login-form');
  const errorDiv  = document.getElementById('login-error');

  if (!loginForm) return;

  loginForm.addEventListener('submit', async function (e) {
    e.preventDefault();

    const emailEl    = document.getElementById('email');
    const passwordEl = document.getElementById('password');

    if (!emailEl || !passwordEl) return;

    const email    = emailEl.value.trim();
    const password = passwordEl.value;

    if (!email || !password) {
      showError('Please enter email and password.');
      return;
    }

    try {
      const res = await fetch('/api/auth/login', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ email, password }),
      });

      const data = await res.json();

      if (!res.ok) {
        showError(data.error?.message || data.error || data.message || 'Login failed. Please try again.');
        return;
      }

      // Store tokens and user state
      const accessToken = data.access_token || (data.data && data.data.access_token);
      const refreshToken = data.refresh_token || (data.data && data.data.refresh_token);
      const user = data.user || (data.data && data.data.user);

      if (accessToken) {
        sessionStorage.setItem('sc_access_token', accessToken);
        localStorage.setItem('sc_access_token', accessToken);
      }
      if (refreshToken) {
        localStorage.setItem('sc_refresh_token', refreshToken);
      }
      if (user) {
        localStorage.setItem('sc_user', JSON.stringify(user));
      }

      // Redirect based on server response redirect URL or role + verification state
      const redirectUrl = data.redirect || (data.data && data.data.redirect);
      if (redirectUrl) {
        window.location.assign(redirectUrl);
        return;
      }

      const role = user ? user.role : (data.role || 'citizen');
      const isVerified = user ? user.verified : false;

      if (role === 'admin') {
        window.location.assign('/admin/dashboard');
      } else if (role === 'officer') {
        window.location.assign('/officer/dashboard');
      } else if (role === 'worker') {
        window.location.assign('/worker/dashboard');
      } else if (role === 'citizen' || role === 'resident') {
        if (!isVerified) {
          window.location.assign('/citizen/verify-ward');
        } else {
          window.location.assign('/citizen/dashboard');
        }
      } else {
        window.location.assign('/citizen/dashboard');
      }


    } catch (err) {
      console.error('Login error:', err);
      showError('Network error. Please check your connection.');
    }
  });

  function showError(msg) {
    if (errorDiv) {
      errorDiv.textContent = msg;
      errorDiv.style.display = 'block';
    } else {
      alert(msg);
    }
  }
});
