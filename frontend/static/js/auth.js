/* ═══════════════════════════════════════════════════════
   BizAL — auth.js  v4
   JWT token storage, refresh, apiFetch wrapper.
   Supports cross-origin dev setup (port 8000/8001).
   Requires ui.js (for toast, esc).

   L-2 FIX: Access tokens are now stored in memory (a module-level variable)
   rather than localStorage. localStorage is readable by any JS on the page,
   making access tokens trivially exfiltrable via XSS. An in-memory access
   token disappears on page unload — the refresh token in localStorage is
   used to re-issue a new access token on the next page load, which is the
   standard SPA pattern for JWT hardening.

   Refresh tokens remain in localStorage so sessions survive page reloads.
   The long-term hardening path is to move refresh tokens to an httpOnly
   Secure SameSite=Strict cookie (requires a backend change to the refresh
   endpoint), but that is an architectural change out of scope here.

   Legacy keys ('access', 'refresh', 'bizal-admin-token') are cleared on
   logout and on first load to avoid stale plaintext tokens lingering for
   users who were logged in before this change.
═══════════════════════════════════════════════════════ */

/* ── API base URL (same-origin prod, cross-port dev) ── */
const API_BASE = (() => {
  const h = window.location.hostname;
  if (h === 'localhost' || h === '127.0.0.1') {
    // Use the actual port the page is served from.
    // - Port 8000 = main domain (auth endpoints, account page)
    // - Port 8001 = tenant subdomain (tenant APIs + tenant-scoped auth)
    // Auth endpoints (/auth/login/, /auth/token/refresh/) exist on both ports,
    // so using window.location.port is safe and avoids CORS issues.
    return `http://localhost:${window.location.port || 8000}`;
  }
  return '';   // same-origin in production
})();

// L-3 FIX: On port 8001 in local dev, TenantMiddleware resolves the tenant
// from the *session* when no `?tenant=` query param is present on the
// request (see tenants/middleware.py "Strategy B"). That session write only
// happens on the page's own GET request; a same-origin fetch() call still
// sends cookies, but if that session cookie is missing/late for any reason
// (private window, cookie blocked, container restart resetting the session
// cache, etc.) the middleware 404s with "visit with ?tenant=<slug> first" —
// which surfaces to the user as a confusing blank "not found" error,
// notably right after a successful register-then-auto-login. The same root
// cause was already patched for /api/bookings/ and /api/orders/ by passing
// `?tenant=` explicitly; do the same here for every dev API call instead of
// leaning on session continuity.
function _devTenantSlug() {
  if (window.location.hostname !== 'localhost' && window.location.hostname !== '127.0.0.1') return '';
  const fromQuery = new URLSearchParams(window.location.search).get('tenant');
  if (fromQuery) return fromQuery;
  return localStorage.getItem('tenant_slug') || '';
}

const Auth = (() => {
  const REFRESH_KEY = 'bizal_refresh';

  // L-2 FIX: Access token lives only in memory — never in localStorage.
  // It is re-issued from the refresh token on every page load via
  // refreshAccess(). This means a stolen XSS payload cannot read
  // the access token from localStorage; it can only steal the refresh
  // token, which is still in localStorage (long-term fix: httpOnly cookie).
  let _accessToken  = null;
  let _refreshPromise = null;

  // On load, scrub any legacy plaintext access tokens that may have been
  // written by auth.js v1–v3. Don't clear the refresh token — we still
  // need it to restore the session.
  ['bizal_access', 'access', 'bizal-admin-token'].forEach(k => localStorage.removeItem(k));

  /* ── Token storage ──────────────────────────────────── */
  function getAccess()  { return _accessToken; }
  function getRefresh() { return localStorage.getItem(REFRESH_KEY) || localStorage.getItem('refresh') || null; }
  function setTokens(access, refresh) {
    _accessToken = access;                          // memory only
    if (refresh) {
      localStorage.setItem(REFRESH_KEY, refresh);
      localStorage.setItem('refresh', refresh);    // keep legacy key in sync
    }
  }
  function clearTokens() {
    _accessToken = null;
    ['bizal_refresh', 'refresh', 'bizal-admin-token'].forEach(k => localStorage.removeItem(k));
  }
  function isLoggedIn() { return !!(_accessToken || getRefresh()); }

  /* ── JWT decode (client-side only, no verify) ────────── */
  function parseJWT(token) {
    try { return JSON.parse(atob(token.split('.')[1].replace(/-/g,'+').replace(/_/g,'/'))); }
    catch { return null; }
  }

  /* ── Refresh access token ───────────────────────────── */
  async function refreshAccess() {
    if (_refreshPromise) return _refreshPromise;
    _refreshPromise = (async () => {
      const refresh = getRefresh();
      if (!refresh) throw new Error('no_refresh');
      const r = await fetch(API_BASE + '/api/auth/token/refresh/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh }),
      });
      if (!r.ok) { clearTokens(); throw new Error('refresh_failed'); }
      const d = await r.json();
      setTokens(d.access, d.refresh || null);
      return d.access;
    })();
    // NOTE: .finally() returns its OWN derived promise that rejects
    // whenever _refreshPromise does. That derived promise was previously
    // left dangling with no handler — so even when a caller correctly
    // catches the *original* _refreshPromise rejection (e.g. checkAuth()'s
    // try/catch around a plain "not logged in" no_refresh case), this
    // second, unrelated promise chain still triggered a browser console
    // "Uncaught (in promise)" warning. The .catch(() => {}) here only
    // silences that harmless duplicate; it has no effect on the rejection
    // callers actually see and handle via the returned _refreshPromise.
    _refreshPromise.finally(() => { _refreshPromise = null; }).catch(() => {});
    return _refreshPromise;
  }

  /* ── Fetch with auto-refresh ────────────────────────── */
  async function apiFetch(endpoint, options = {}, retry = true) {
    // If no access token in memory, try to restore from refresh token
    // (covers page-reload case where memory was cleared).
    if (!_accessToken && getRefresh()) {
      try { await refreshAccess(); } catch { /* will 401 below */ }
    }
    const token = getAccess();
    const isFormData = options.body instanceof FormData;

    // For FormData, do NOT set Content-Type — the browser must set it
    // automatically so it includes the multipart boundary. For all other
    // bodies, default to application/json, but allow callers to override.
    const headers = isFormData
      ? { ...(options.headers || {}) }
      : { 'Content-Type': 'application/json', ...(options.headers || {}) };

    if (token) headers['Authorization'] = `Bearer ${token}`;

    // Serialize plain objects to JSON. Skip strings (already serialized)
    // and FormData (must be passed as-is so the browser keeps the boundary).
    let body = options.body;
    if (body && typeof body !== 'string' && !isFormData) {
      body = JSON.stringify(body);
    }

    let url = API_BASE + '/api' + endpoint;
    const devSlug = _devTenantSlug();
    if (devSlug && window.location.port === '8001' && !/[?&]tenant=/.test(url)) {
      url += (url.includes('?') ? '&' : '?') + 'tenant=' + encodeURIComponent(devSlug);
    }
    const r = await fetch(url, { ...options, headers, body });

    if (r.status === 401 && retry) {
      try {
        await refreshAccess();
        // Pass a fresh options copy — body already serialized above, headers
        // need the new token, so let the recursive call rebuild them cleanly.
        return apiFetch(endpoint, { ...options, body }, false);
      } catch {
        clearTokens();
        window.location.href = '/';
        return r;
      }
    }
    return r;
  }

  /* ── HTTP helpers ───────────────────────────────────── */
  const get    = (ep, opts = {})  => apiFetch(ep, { method: 'GET',    ...opts });
  const post   = (ep, body, opts) => apiFetch(ep, { method: 'POST',   body, ...opts });
  const patch  = (ep, body, opts) => apiFetch(ep, { method: 'PATCH',  body, ...opts });
  const put    = (ep, body, opts) => apiFetch(ep, { method: 'PUT',    body, ...opts });
  const del    = (ep, opts = {})  => apiFetch(ep, { method: 'DELETE', ...opts });

  /* ── Login ──────────────────────────────────────────── */
  async function login(email, password) {
    const devSlug = _devTenantSlug();
    let loginUrl = API_BASE + '/api/auth/login/';
    if (devSlug && window.location.port === '8001') {
      loginUrl += '?tenant=' + encodeURIComponent(devSlug);
    }
    const r = await fetch(loginUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    if (!r.ok) {
      const d = await r.json().catch(() => ({}));
      const err = new Error(d.detail || d.non_field_errors?.[0] || 'Kredencialet janë të gabuara.');
      // 403 from CustomTokenObtainPairView when a tenant-owning user tries
      // to log in from the main domain: the backend already knows which
      // tenant they belong to (redirect_slug) — surface it on the error
      // instead of discarding it, so the caller can send them to the right
      // place instead of showing a generic "try again" message.
      if (d.redirect_slug) err.redirectSlug = d.redirect_slug;
      throw err;
    }
    const d = await r.json();
    setTokens(d.access, d.refresh);
    return d;
  }

  /* ── Logout ─────────────────────────────────────────── */
  async function logout(redirectTo = '/') {
    const refresh = getRefresh();
    if (refresh) {
      // BUGFIX: previously called raw fetch() with getAccess() directly.
      // _accessToken is memory-only and is null on a fresh page load until
      // some other authenticated call triggers refreshAccess() — if logout()
      // was the FIRST authenticated action on the page (e.g. user lands on
      // account.html and immediately clicks "Log out"), this sent
      // `Authorization: Bearer null`, which the backend correctly rejected
      // with 401. apiFetch() already has the "refresh first if no in-memory
      // token" check (see top of apiFetch), so routing through it here gets
      // a valid token — and its 401-retry-once logic — for free, instead of
      // duplicating that logic badly.
      await apiFetch('/auth/logout/', {
        method: 'POST',
        body: { refresh },
      }, false).catch(() => {});
    }
    clearTokens();
    window.location.href = redirectTo;
  }

  /* ── Pick up tokens from URL (cross-origin redirect) ── */
  function pickupTokensFromUrl() {
    const params = new URLSearchParams(window.location.search);
    const a = params.get('access_token');
    const r = params.get('refresh_token');
    if (a) {
      setTokens(a, r || null);
      params.delete('access_token');
      params.delete('refresh_token');
      const qs = params.toString();
      window.history.replaceState({}, '', window.location.pathname + (qs ? '?' + qs : ''));
    }
  }

  /* ── Get current user ───────────────────────────────── */
  async function me() {
    const r = await get('/auth/me/');
    if (!r.ok) return null;
    return r.json();
  }

  /* ── Convenience aliases used by older templates ────── */
  function save(access, refresh) { setTokens(access, refresh); }
  function clear() { clearTokens(); }
  function headers() { const t = getAccess(); return t ? { 'Authorization': `Bearer ${t}` } : {}; }

  return {
    API_BASE,
    getAccess, getRefresh, setTokens, clearTokens, isLoggedIn, parseJWT,
    apiFetch, get, post, patch, put, del,
    login, logout, me,
    refreshAccess,
    pickupTokensFromUrl,
    // legacy aliases
    save, clear, headers,
  };
})();
