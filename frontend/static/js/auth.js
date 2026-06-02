/* auth.js — Shared auth modal for all tenant pages
   Loaded by tenant.js automatically                */

(function initAuth() {
  const { API, show, hide } = window.BizAL;

  function updateAuthNav() {
    const authEl = document.getElementById('nav-auth');
    const drawerAuth = document.getElementById('drawer-auth');
    if (!authEl) return;

    if (API.isLoggedIn()) {
      authEl.innerHTML = `<button class="btn btn-outline btn-sm" id="btn-logout">Dil</button>`;
      if (drawerAuth) drawerAuth.innerHTML = `<button class="btn btn-outline btn-sm" style="width:100%" id="drawer-logout">Dil</button>`;

      const doLogout = async () => {
        const { refresh } = API.getTokens();
        try { await API.post('/auth/logout/', { refresh }); } catch {}
        API.clearTokens();
        window.location.reload();
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

      document.getElementById('btn-login')?.addEventListener('click', () => openAuthModal('login'));
      document.getElementById('btn-register')?.addEventListener('click', () => openAuthModal('register'));
      document.getElementById('drawer-login')?.addEventListener('click', () => openAuthModal('login'));
      document.getElementById('drawer-register')?.addEventListener('click', () => openAuthModal('register'));
    }
  }

  function openAuthModal(tab = 'login') {
    const modal = document.getElementById('auth-modal');
    if (!modal) return;
    show(modal);
    renderAuthTab(tab);

    document.getElementById('close-auth')?.addEventListener('click', () => hide(modal));
    modal.querySelector('.modal-backdrop')?.addEventListener('click', () => hide(modal));
    document.getElementById('tab-login')?.addEventListener('click', () => renderAuthTab('login'));
    document.getElementById('tab-register')?.addEventListener('click', () => renderAuthTab('register'));
  }

  function renderAuthTab(tab) {
    document.querySelectorAll('#auth-tabs .tab-btn').forEach(b =>
      b.classList.toggle('active', b.id === `tab-${tab}`)
    );
    const content = document.getElementById('auth-form-content');
    const errEl   = document.getElementById('auth-error');
    if (errEl) hide(errEl);

    if (tab === 'login') {
      content.innerHTML = `
        <input class="auth-input" id="ai-email" type="email" placeholder="Email" autocomplete="email" />
        <input class="auth-input" id="ai-pass"  type="password" placeholder="Fjalëkalim" autocomplete="current-password" />
        <button class="btn btn-primary btn-block" id="ai-submit" style="margin-top:4px">Hyr</button>`;
      document.getElementById('ai-submit')?.addEventListener('click', doLogin);
      document.getElementById('ai-pass')?.addEventListener('keydown', e => { if (e.key === 'Enter') doLogin(); });
    } else {
      content.innerHTML = `
        <input class="auth-input" id="ai-name"  type="text"     placeholder="Emri i plotë" autocomplete="name" />
        <input class="auth-input" id="ai-email" type="email"    placeholder="Email" autocomplete="email" />
        <input class="auth-input" id="ai-pass"  type="password" placeholder="Fjalëkalim (min 8 karaktere)" autocomplete="new-password" />
        <button class="btn btn-primary btn-block" id="ai-submit" style="margin-top:4px">Regjistrohu</button>`;
      document.getElementById('ai-submit')?.addEventListener('click', doRegister);
    }
  }

  function showAuthError(msg) {
    const e = document.getElementById('auth-error');
    if (!e) return;
    e.textContent = msg;
    show(e);
  }

  async function doLogin() {
    const email    = document.getElementById('ai-email')?.value.trim();
    const password = document.getElementById('ai-pass')?.value;
    const resp = await API.post('/auth/login/', { email, password });
    const data = await resp.json();
    if (!resp.ok) { showAuthError(data.detail || 'Email ose fjalëkalim i gabuar.'); return; }
    API.saveTokens(data.access, data.refresh);
    hide(document.getElementById('auth-modal'));
    updateAuthNav();
    window.BizAL.toast('Mirë se vini! ✓');
  }

  async function doRegister() {
    const full_name = document.getElementById('ai-name')?.value.trim();
    const email     = document.getElementById('ai-email')?.value.trim();
    const password  = document.getElementById('ai-pass')?.value;

    const r1 = await API.post('/auth/register/', { full_name, email, password });
    if (!r1.ok) {
      const d = await r1.json();
      showAuthError(Object.values(d).flat().join(' '));
      return;
    }
    const r2   = await API.post('/auth/login/', { email, password });
    const data = await r2.json();
    if (!r2.ok) { showAuthError('Regjistrim i suksesshëm! Hyni tani.'); renderAuthTab('login'); return; }
    API.saveTokens(data.access, data.refresh);
    hide(document.getElementById('auth-modal'));
    updateAuthNav();
    window.BizAL.toast('Llogaria u krijua! ✓');
  }

  // Expose so pages can call openAuthModal directly
  window.BizAL.openAuthModal  = openAuthModal;
  window.BizAL.updateAuthNav  = updateAuthNav;

  // Run on DOM ready
  document.addEventListener('DOMContentLoaded', updateAuthNav);
})();
