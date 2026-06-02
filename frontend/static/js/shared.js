/* =============================================
   BizAL — shared.js
   Theme toggle + Mobile nav + Auth modal
   Loaded on EVERY page (main + tenant)
   ============================================= */

// ── Theme ──────────────────────────────────────────────────
const ThemeManager = (() => {
  const KEY = 'bizal_theme';

  function get()  { return localStorage.getItem(KEY) || 'light'; }
  function apply(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem(KEY, theme);
    document.querySelectorAll('.theme-toggle').forEach(btn => {
      btn.textContent = theme === 'dark' ? '☀️' : '🌙';
      btn.title = theme === 'dark' ? 'Kalo në temën e ndritshme' : 'Kalon në temën e errët';
    });
  }
  function toggle() { apply(get() === 'dark' ? 'light' : 'dark'); }
  function init()   { apply(get()); }

  return { get, apply, toggle, init };
})();

// ── Mobile nav ──────────────────────────────────────────────
function initMobileNav() {
  const toggle = document.getElementById('nav-toggle');
  const drawer = document.getElementById('nav-drawer');
  if (!toggle || !drawer) return;

  toggle.addEventListener('click', e => {
    e.stopPropagation();
    drawer.classList.toggle('hidden');
  });
  document.addEventListener('click', e => {
    if (!toggle.contains(e.target) && !drawer.contains(e.target)) {
      drawer.classList.add('hidden');
    }
  });

  // Bind theme toggle inside drawer too
  document.querySelectorAll('.theme-toggle').forEach(btn => {
    btn.addEventListener('click', ThemeManager.toggle);
  });
}

// ── Active nav link ─────────────────────────────────────────
function markActiveNav() {
  const path = window.location.pathname.replace(/\/+$/, '') || '/';
  document.querySelectorAll('.nav-link, .drawer-link').forEach(a => {
    const href = (a.getAttribute('href') || '/').replace(/\/+$/, '') || '/';
    const isActive = href === path || (href !== '/' && path.startsWith(href));
    a.classList.toggle('active', isActive);
  });
}

// ── Auth ────────────────────────────────────────────────────
const Auth = (() => {
  const ACCESS_KEY  = 'bizal_access';
  const REFRESH_KEY = 'bizal_refresh';

  function isLoggedIn() { return !!localStorage.getItem(ACCESS_KEY); }
  function getTokens()  { return { access: localStorage.getItem(ACCESS_KEY), refresh: localStorage.getItem(REFRESH_KEY) }; }
  function saveTokens(a, r) { localStorage.setItem(ACCESS_KEY, a); if (r) localStorage.setItem(REFRESH_KEY, r); }
  function clearTokens()    { localStorage.removeItem(ACCESS_KEY); localStorage.removeItem(REFRESH_KEY); }

  async function apiFetch(method, url, body) {
    const { access } = getTokens();
    const headers = { 'Content-Type': 'application/json' };
    if (access) headers['Authorization'] = `Bearer ${access}`;
    const resp = await fetch(url, { method, headers, body: body ? JSON.stringify(body) : undefined });
    return resp;
  }

  function updateNavAuth() {
    const authEl     = document.getElementById('nav-auth');
    const drawerAuth = document.getElementById('drawer-auth');
    if (!authEl) return;

    if (isLoggedIn()) {
      authEl.innerHTML     = `<button class="btn btn-outline btn-sm" id="btn-logout">Dil</button>`;
      if (drawerAuth) drawerAuth.innerHTML = `<button class="btn btn-ghost" style="flex:1" id="drawer-logout">Dil</button>`;

      const doLogout = async () => {
        const { refresh } = getTokens();
        try { await apiFetch('POST', '/api/auth/logout/', { refresh }); } catch {}
        clearTokens();
        window.location.href = '/';
      };
      document.getElementById('btn-logout')?.addEventListener('click', doLogout);
      document.getElementById('drawer-logout')?.addEventListener('click', doLogout);
    } else {
      authEl.innerHTML = `
        <button class="btn btn-outline btn-sm" id="btn-login">Hyr</button>
        <button class="btn btn-primary btn-sm" id="btn-register">Regjistrohu</button>`;
      if (drawerAuth) drawerAuth.innerHTML = `
        <button class="btn btn-outline btn-sm" style="flex:1" id="drawer-login">Hyr</button>
        <button class="btn btn-primary btn-sm" style="flex:1" id="drawer-register">Regjistrohu</button>`;

      ['btn-login','drawer-login'].forEach(id =>
        document.getElementById(id)?.addEventListener('click', () => openModal('login')));
      ['btn-register','drawer-register'].forEach(id =>
        document.getElementById(id)?.addEventListener('click', () => openModal('register')));
    }
  }

  function openModal(tab = 'login') {
    const modal = document.getElementById('auth-modal');
    if (!modal) return;
    modal.classList.remove('hidden');
    renderTab(tab);

    const close = () => modal.classList.add('hidden');
    document.getElementById('close-auth')?.addEventListener('click', close);
    modal.querySelector('.modal-backdrop')?.addEventListener('click', close);
    document.getElementById('tab-login')?.addEventListener('click',    () => renderTab('login'));
    document.getElementById('tab-register')?.addEventListener('click', () => renderTab('register'));
  }

  function renderTab(tab) {
    document.querySelectorAll('#auth-tabs .tab-btn').forEach(b =>
      b.classList.toggle('active', b.id === `tab-${tab}`));
    const content = document.getElementById('auth-form-content');
    const errEl   = document.getElementById('auth-error');
    if (errEl) errEl.classList.add('hidden');

    if (tab === 'login') {
      content.innerHTML = `
        <input class="auth-input" id="ai-email" type="email"    placeholder="Email" autocomplete="email" />
        <input class="auth-input" id="ai-pass"  type="password" placeholder="Fjalëkalim" autocomplete="current-password" />
        <button class="btn btn-primary btn-block" id="ai-submit" style="margin-top:4px">Hyr</button>`;
      document.getElementById('ai-submit')?.addEventListener('click', doLogin);
      document.getElementById('ai-pass')?.addEventListener('keydown', e => { if (e.key==='Enter') doLogin(); });
    } else {
      content.innerHTML = `
        <input class="auth-input" id="ai-name"  type="text"     placeholder="Emri i plotë" autocomplete="name" />
        <input class="auth-input" id="ai-email" type="email"    placeholder="Email" autocomplete="email" />
        <input class="auth-input" id="ai-pass"  type="password" placeholder="Fjalëkalim (min 8 karaktere)" autocomplete="new-password" />
        <button class="btn btn-primary btn-block" id="ai-submit" style="margin-top:4px">Regjistrohu</button>`;
      document.getElementById('ai-submit')?.addEventListener('click', doRegister);
    }
  }

  function showError(msg) {
    const e = document.getElementById('auth-error');
    if (!e) return;
    e.textContent = msg;
    e.classList.remove('hidden');
  }

  async function doLogin() {
    const email    = document.getElementById('ai-email')?.value.trim();
    const password = document.getElementById('ai-pass')?.value;
    const resp = await apiFetch('POST', '/api/auth/login/', { email, password });
    const data = await resp.json();
    if (!resp.ok) { showError(data.detail || 'Email ose fjalëkalim i gabuar.'); return; }
    saveTokens(data.access, data.refresh);
    document.getElementById('auth-modal')?.classList.add('hidden');
    updateNavAuth();
    showToast('Mirë se vini! ✓');
  }

  async function doRegister() {
    const full_name = document.getElementById('ai-name')?.value.trim();
    const email     = document.getElementById('ai-email')?.value.trim();
    const password  = document.getElementById('ai-pass')?.value;
    const r1 = await apiFetch('POST', '/api/auth/register/', { full_name, email, password });
    if (!r1.ok) { const d=await r1.json(); showError(Object.values(d).flat().join(' ')); return; }
    const r2   = await apiFetch('POST', '/api/auth/login/', { email, password });
    const data = await r2.json();
    saveTokens(data.access, data.refresh);
    document.getElementById('auth-modal')?.classList.add('hidden');
    updateNavAuth();
    showToast('Llogaria u krijua me sukses! ✓');
  }

  return { isLoggedIn, getTokens, saveTokens, clearTokens, apiFetch, updateNavAuth, openModal };
})();

// ── Toast ────────────────────────────────────────────────────
function showToast(message, type = 'success', duration = 3500) {
  let container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    container.style.cssText = 'position:fixed;bottom:80px;right:24px;z-index:9999;display:flex;flex-direction:column;gap:8px;pointer-events:none';
    document.body.appendChild(container);
  }
  const colors = { success: '#10B981', error: '#EF4444', info: '#2563EB' };
  const t = document.createElement('div');
  t.style.cssText = `background:${colors[type]||colors.success};color:#fff;padding:12px 20px;border-radius:8px;font-size:14px;font-weight:600;box-shadow:0 4px 16px rgba(0,0,0,.2);animation:toastIn .2s ease;pointer-events:auto`;
  t.textContent = message;
  container.appendChild(t);
  setTimeout(() => { t.style.opacity='0'; t.style.transition='opacity .3s'; setTimeout(()=>t.remove(), 300); }, duration);
}

const style = document.createElement('style');
style.textContent = '@keyframes toastIn{from{opacity:0;transform:translateX(40px)}to{opacity:1;transform:none}}';
document.head.appendChild(style);

// ── Init on DOM ready ────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  ThemeManager.init();
  initMobileNav();
  markActiveNav();
  Auth.updateNavAuth();
});

// ── Global exports ───────────────────────────────────────────
window.BizAL = window.BizAL || {};
Object.assign(window.BizAL, {
  Auth, ThemeManager, showToast,
  // Legacy compat used by page scripts
  isLoggedIn:   Auth.isLoggedIn,
  getTokens:    Auth.getTokens,
  saveTokens:   Auth.saveTokens,
  clearTokens:  Auth.clearTokens,
  openAuthModal: Auth.openModal,
  toast:        showToast,
  show: el => el?.classList.remove('hidden'),
  hide: el => el?.classList.add('hidden'),
  toggle: (el, cond) => el?.classList.toggle('hidden', !cond),
  $:  (sel, ctx=document) => ctx.querySelector(sel),
  $$: (sel, ctx=document) => [...ctx.querySelectorAll(sel)],
  setText:      (sel, t) => { const el=typeof sel==='string'?document.querySelector(sel):sel; if(el) el.textContent=t; },
  setHTML:      (sel, h) => { const el=typeof sel==='string'?document.querySelector(sel):sel; if(el) el.innerHTML=h; },
  showFeedback: (el, msg, type='success') => { if(!el)return; el.textContent=msg; el.className=`feedback ${type}`; el.classList.remove('hidden'); setTimeout(()=>el.classList.add('hidden'),5000); },
  starHTML:     r => '★'.repeat(r)+'☆'.repeat(5-r),
  formatDate:   d => d ? new Date(d).toLocaleDateString('sq-AL',{year:'numeric',month:'long',day:'numeric'}) : '',
  formatPrice:  (a,c='ALL') => `${Number(a).toLocaleString('sq-AL')} ${c}`,
  debounce:     (fn,d=400) => { let t; return (...a)=>{clearTimeout(t);t=setTimeout(()=>fn(...a),d)}; },
});
