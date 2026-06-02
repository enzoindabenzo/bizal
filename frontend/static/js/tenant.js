/* =============================================
   BizAL — tenant.js  |  Branding Engine v2
   Loads /api/tenant/info/ and applies all
   tenant-specific branding to every page.
   Also handles dark/light theme persistence.
   ============================================= */

(async function TenantBranding() {

  // ── Theme (must run before anything renders) ──────────────────
  (function initTheme() {
    const saved = localStorage.getItem('bizal-theme') || 'light';
    document.documentElement.setAttribute('data-theme', saved);
    const icon = saved === 'dark' ? '☀️' : '🌙';
    document.querySelectorAll('.theme-toggle').forEach(b => b.textContent = icon);
  })();

  function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme') || 'light';
    const next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('bizal-theme', next);
    const icon = next === 'dark' ? '☀️' : '🌙';
    document.querySelectorAll('.theme-toggle').forEach(b => b.textContent = icon);
  }

  // Bind theme toggles (both navbar and drawer)
  document.querySelectorAll('.theme-toggle').forEach(btn => {
    btn.addEventListener('click', toggleTheme);
  });

  // ── Fetch tenant info ─────────────────────────────────────────
  async function loadInfo() {
    try {
      const resp = await fetch('/api/tenant/info/');
      if (!resp.ok) return null;
      return await resp.json();
    } catch { return null; }
  }

  // ── Apply brand colors ────────────────────────────────────────
  function applyColors(t) {
    const root = document.documentElement;
    const primary = t.primary_color || '#2563EB';
    const accent  = t.accent_color  || '#F59E0B';
    root.style.setProperty('--primary', primary);
    root.style.setProperty('--accent',  accent);
    const hex = primary.replace('#', '');
    const r = parseInt(hex.slice(0, 2), 16);
    const g = parseInt(hex.slice(2, 4), 16);
    const b = parseInt(hex.slice(4, 6), 16);
    root.style.setProperty('--primary-rgb', `${r},${g},${b}`);
    // Derive dark variant
    const darken = (c, amt) => Math.max(0, Math.min(255, c - amt));
    root.style.setProperty('--primary-dark', `rgb(${darken(r,20)},${darken(g,20)},${darken(b,20)})`);
  }

  // ── Apply font ────────────────────────────────────────────────
  function applyFont(t) {
    if (!t.font_family || t.font_family === 'Inter') return;
    const link = document.createElement('link');
    link.rel  = 'stylesheet';
    link.href = `https://fonts.googleapis.com/css2?family=${encodeURIComponent(t.font_family)}:wght@400;500;600;700;800;900&display=swap`;
    document.head.appendChild(link);
    document.documentElement.style.setProperty('--font', `'${t.font_family}', system-ui, sans-serif`);
  }

  // ── Apply page meta ───────────────────────────────────────────
  function applyMeta(t) {
    document.title = t.site_title || t.name || 'BizAL';
    const desc = document.getElementById('meta-description');
    if (desc) desc.content = t.meta_description || t.tagline || '';
    const fav = document.getElementById('favicon');
    if (fav && t.logo_url) fav.href = t.logo_url;
  }

  // ── Apply navbar ──────────────────────────────────────────────
  function applyNav(t) {
    const titleEl = document.getElementById('nav-title');
    if (titleEl) titleEl.textContent = t.site_title || t.name;

    const logoEl = document.getElementById('nav-logo');
    if (logoEl && t.logo_url) {
      logoEl.src = t.logo_url; logoEl.alt = t.name;
      logoEl.classList.remove('hidden');
    }

    // Food businesses: show Menu tab, rename services
    const isFood = ['restaurant', 'bar', 'bakery', 'delivery_kitchen'].includes(t.business_type);
    if (isFood) {
      document.getElementById('nav-menu-link')?.classList.remove('hidden');
      document.getElementById('drawer-menu')?.classList.remove('hidden');
      const svcLink = document.getElementById('nav-services-link');
      const drawerSvc = document.getElementById('drawer-services');
      if (svcLink) svcLink.style.display = 'none';
      if (drawerSvc) drawerSvc.style.display = 'none';
    }

    // Show contact link if feature enabled
    if (t.has_contact) {
      document.getElementById('nav-contact-link')?.classList.remove('hidden');
      document.getElementById('drawer-contact')?.classList.remove('hidden');
    }

    // Show blog link if enterprise
    if (t.has_blog) {
      document.getElementById('nav-blog-link')?.classList.remove('hidden');
      document.getElementById('drawer-blog')?.classList.remove('hidden');
    }

    // Admin bar for owners/managers (checked in index.js after auth)
    if (t.admin_url) {
      const bar = document.getElementById('admin-bar');
      if (bar) {
        bar.classList.remove('hidden');
        const nameEl = document.getElementById('admin-bar-name');
        if (nameEl) nameEl.textContent = `Admin: ${t.name}`;
        const linkEl = document.getElementById('admin-bar-link');
        if (linkEl) { linkEl.href = t.admin_url; linkEl.textContent = `⚙️ Paneli Admin — ${t.slug}.bizal.al`; }
      }
    }
  }

  // ── Apply hero ────────────────────────────────────────────────
  function applyHero(t) {
    const titleEl   = document.getElementById('hero-title');
    const taglineEl = document.getElementById('hero-tagline');
    const badgesEl  = document.getElementById('hero-badges');
    const statsEl   = document.getElementById('hero-stats');

    if (titleEl) titleEl.textContent   = t.site_title || t.name;
    if (taglineEl) taglineEl.textContent = t.tagline || '';

    if (badgesEl) {
      const parts = [];
      if (t.city) parts.push(`📍 ${t.city}`);
      if (t.founded_year) parts.push(`🏆 Që nga ${t.founded_year}`);
      if (t.business_hours_text) parts.push(`🕐 ${t.business_hours_text}`);
      badgesEl.innerHTML = parts.map(p => `<span class="hero-badge-item">${p}</span>`).join('');
    }

    if (statsEl && t.plan !== 'starter') {
      statsEl.classList.remove('hidden');
      const yearEl = document.getElementById('stat-years');
      if (yearEl && t.founded_year) {
        yearEl.textContent = new Date().getFullYear() - parseInt(t.founded_year);
      }
    }

    // Show contact button if feature enabled
    const contactBtn = document.getElementById('hero-contact-btn');
    if (contactBtn && t.has_contact) contactBtn.classList.remove('hidden');
  }

  // ── WhatsApp ──────────────────────────────────────────────────
  function applyWhatsApp(t) {
    const btn = document.getElementById('whatsapp-btn');
    if (!btn || !t.whatsapp || t.plan === 'starter') return;
    const num = t.whatsapp.replace(/\D/g, '');
    btn.href = `https://wa.me/${num}`;
    btn.classList.remove('hidden');
  }

  // ── Footer ────────────────────────────────────────────────────
  function applyFooter(t) {
    const copyEl = document.getElementById('footer-copy');
    if (copyEl) copyEl.textContent = `© ${new Date().getFullYear()} ${t.name}. Të gjitha të drejtat e rezervuara.`;

    const nameEl = document.getElementById('footer-name');
    if (nameEl) nameEl.textContent = t.name;

    const taglineEl = document.getElementById('footer-tagline');
    if (taglineEl) taglineEl.textContent = t.tagline || '';

    const logoEl = document.getElementById('footer-logo');
    if (logoEl && t.logo_url) { logoEl.src = t.logo_url; logoEl.classList.remove('hidden'); }

    const contactEl = document.getElementById('footer-contact-info');
    if (contactEl) {
      let html = '<h4 class="footer-heading">Kontakt</h4>';
      if (t.phone)   html += `<a href="tel:${t.phone}">📞 ${t.phone}</a>`;
      if (t.email)   html += `<a href="mailto:${t.email}">✉️ ${t.email}</a>`;
      if (t.address) html += `<span>📍 ${t.address}${t.city ? ', ' + t.city : ''}</span>`;
      contactEl.innerHTML = html;
    }

    if (t.plan === 'enterprise') {
      const socialEl  = document.getElementById('footer-social');
      const linksEl   = document.getElementById('social-links');
      if (socialEl && linksEl) {
        let html = '';
        if (t.facebook)  html += `<a href="${t.facebook}"  target="_blank" rel="noopener" style="color:var(--text-muted);text-decoration:none;font-size:14px;transition:var(--transition)">📘 Facebook</a>`;
        if (t.instagram) html += `<a href="${t.instagram}" target="_blank" rel="noopener" style="color:var(--text-muted);text-decoration:none;font-size:14px">📸 Instagram</a>`;
        if (t.tiktok)    html += `<a href="${t.tiktok}"    target="_blank" rel="noopener" style="color:var(--text-muted);text-decoration:none;font-size:14px">🎵 TikTok</a>`;
        if (html) { linksEl.innerHTML = html; socialEl.classList.remove('hidden'); }
      }
    }
  }

  // ── Mobile drawer ─────────────────────────────────────────────
  function initMobileDrawer() {
    const toggle = document.getElementById('nav-toggle');
    const drawer = document.getElementById('nav-drawer-tenant');
    if (!toggle || !drawer) return;

    toggle.addEventListener('click', () => {
      const open = drawer.classList.toggle('open');
      toggle.setAttribute('aria-expanded', open);
      document.body.style.overflow = open ? 'hidden' : '';
    });

    drawer.querySelectorAll('.drawer-link').forEach(link => {
      link.addEventListener('click', () => {
        drawer.classList.remove('open');
        document.body.style.overflow = '';
      });
    });

    // Drawer auth buttons delegate to nav auth
    document.getElementById('drawer-btn-login')?.addEventListener('click', () => {
      drawer.classList.remove('open');
      document.body.style.overflow = '';
      document.getElementById('btn-login')?.click();
    });
    document.getElementById('drawer-btn-register')?.addEventListener('click', () => {
      drawer.classList.remove('open');
      document.body.style.overflow = '';
      document.getElementById('btn-register')?.click();
    });

    // Drawer theme toggle already bound globally above
  }

  // ── Sticky nav shadow ─────────────────────────────────────────
  function initScrollBehavior() {
    const nav = document.getElementById('navbar');
    window.addEventListener('scroll', () => {
      nav?.classList.toggle('scrolled', window.scrollY > 20);
    }, { passive: true });
  }

  // ── Init ──────────────────────────────────────────────────────
  const tenant = await loadInfo();

  initMobileDrawer();
  initScrollBehavior();

  if (!tenant) return; // main domain — stop here

  // Feature flags
  tenant.has_reviews = ['pro', 'enterprise'].includes(tenant.plan);
  tenant.has_blog    = tenant.plan === 'enterprise';
  tenant.has_contact = tenant.plan !== 'starter';
  tenant.admin_url   = `/admin/?tenant=${tenant.slug}`;

  applyColors(tenant);
  applyFont(tenant);
  applyMeta(tenant);
  applyNav(tenant);
  applyHero(tenant);
  applyWhatsApp(tenant);
  applyFooter(tenant);

  window.__BIZAL_TENANT__ = tenant;
  window.dispatchEvent(new CustomEvent('tenantReady', { detail: tenant }));
})();
