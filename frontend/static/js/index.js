/* =============================================
   BizAL — index.js  |  Tenant SPA v2
   Hash-based routing (#home, #services, etc.)
   so URL persists on refresh.
   ============================================= */

// ── API helpers ───────────────────────────────────────────────
const API = {
  _headers(withAuth = true) {
    const h = { 'Content-Type': 'application/json' };
    if (withAuth) {
      const token = localStorage.getItem('bizal_access');
      if (token) h['Authorization'] = 'Bearer ' + token;
    }
    return h;
  },
  get(ep)       { return fetch('/api' + ep, { headers: this._headers() }); },
  post(ep, body){ return fetch('/api' + ep, { method: 'POST',  headers: this._headers(), body: JSON.stringify(body) }); },
  patch(ep, body){ return fetch('/api' + ep, { method: 'PATCH', headers: this._headers(), body: JSON.stringify(body) }); },
  isLoggedIn()  { return !!localStorage.getItem('bizal_access'); },
  saveTokens(a, r){ localStorage.setItem('bizal_access', a); localStorage.setItem('bizal_refresh', r); },
  clearTokens() { localStorage.removeItem('bizal_access'); localStorage.removeItem('bizal_refresh'); },
  getTokens()   { return { access: localStorage.getItem('bizal_access'), refresh: localStorage.getItem('bizal_refresh') }; },
};

// ── State ─────────────────────────────────────────────────────
let currentSection = 'home';
let tenant = null;
let reviewRating = 0;
const loadedSections = new Set();

// ── Toast ─────────────────────────────────────────────────────
function toast(msg, type = 'success') {
  const container = document.getElementById('toast-container') || (() => {
    const c = document.createElement('div');
    c.className = 'toast-container'; c.id = 'toast-container';
    document.body.appendChild(c); return c;
  })();
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  container.appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; el.style.transform = 'translateX(20px)'; el.style.transition = '.3s'; setTimeout(() => el.remove(), 300); }, 3500);
}

function showFeedback(el, msg, type) {
  if (!el) return;
  el.textContent = msg; el.className = `feedback ${type}`; el.classList.remove('hidden');
}

function starHTML(n) {
  return Array.from({ length: 5 }, (_, i) => `<span style="color:${i < n ? 'var(--accent)' : 'var(--border-strong)'}">★</span>`).join('');
}

function formatDate(d) {
  if (!d) return '';
  return new Date(d).toLocaleDateString('sq-AL', { day: 'numeric', month: 'long', year: 'numeric' });
}

function formatPrice(p) {
  if (!p && p !== 0) return '';
  return parseFloat(p).toLocaleString('sq-AL', { style: 'currency', currency: 'ALL', maximumFractionDigits: 0 });
}

// ── Hash-based Router ────────────────────────────────────────
// URL: tenant.localhost:8001/#services  →  persists on refresh ✓
const VALID_SECTIONS = ['home', 'services', 'menu', 'reviews', 'blog', 'contact'];

function getSectionFromHash() {
  const hash = window.location.hash.slice(1); // remove '#'
  return VALID_SECTIONS.includes(hash) ? hash : 'home';
}

function showSection(name, updateHash = true) {
  if (!VALID_SECTIONS.includes(name)) name = 'home';

  // Hide all sections
  document.querySelectorAll('.section, .hero').forEach(s => {
    s.classList.add('hidden');
  });

  // Show target
  const target = document.getElementById(`section-${name}`);
  if (target) target.classList.remove('hidden');

  // Update nav links active state
  document.querySelectorAll('.nav-link, .drawer-link').forEach(l => {
    l.classList.toggle('active', l.dataset.section === name);
  });

  currentSection = name;
  window.scrollTo({ top: 0, behavior: 'smooth' });

  // Update URL hash without page reload
  if (updateHash) {
    const newHash = name === 'home' ? '' : `#${name}`;
    if (window.location.hash !== (newHash || '#') && window.location.hash !== newHash) {
      window.history.pushState(null, '', newHash || window.location.pathname);
    }
  }

  // Lazy-load data (only once per section)
  if (!loadedSections.has(name)) {
    loadedSections.add(name);
    const loaders = {
      services: loadListings,
      menu: loadMenu,
      reviews: loadReviews,
      blog: loadBlog,
      contact: loadContactInfo,
    };
    if (loaders[name]) loaders[name]();
  }
}

// Handle browser back/forward and refresh
window.addEventListener('hashchange', () => {
  showSection(getSectionFromHash(), false);
});

// ── Navigation Init ───────────────────────────────────────────
function initNav() {
  document.querySelectorAll('[data-section]').forEach(link => {
    link.addEventListener('click', e => {
      e.preventDefault();
      showSection(link.dataset.section);
      // Close mobile drawer
      document.getElementById('nav-drawer-tenant')?.classList.remove('open');
      document.body.style.overflow = '';
    });
  });

  document.getElementById('hero-cta-btn')?.addEventListener('click', () => {
    const t = window.__BIZAL_TENANT__;
    if (t && ['restaurant', 'bar', 'bakery', 'delivery_kitchen'].includes(t.business_type)) {
      showSection('menu');
    } else {
      showSection('services');
    }
  });
  document.getElementById('hero-contact-btn')?.addEventListener('click', () => showSection('contact'));
}

// ── Auth ──────────────────────────────────────────────────────
function updateAuthUI() {
  const authEl = document.getElementById('nav-auth');
  if (!authEl) return;

  if (API.isLoggedIn()) {
    authEl.innerHTML = `
      <span id="user-greeting" style="font-size:13px;color:var(--text-muted)">...</span>
      <button class="btn btn-ghost btn-sm" id="btn-logout">Dil</button>
    `;
    document.getElementById('btn-logout')?.addEventListener('click', logout);
    loadMe();
    document.getElementById('review-form-wrap')?.classList.remove('hidden');
  } else {
    authEl.innerHTML = `
      <button class="btn btn-outline btn-sm" id="btn-login">Hyr</button>
      <button class="btn btn-primary btn-sm" id="btn-register">Regjistrohu</button>
    `;
    document.getElementById('btn-login')?.addEventListener('click', () => openAuthModal('login'));
    document.getElementById('btn-register')?.addEventListener('click', () => openAuthModal('register'));
    document.getElementById('review-form-wrap')?.classList.add('hidden');
  }
}

async function loadMe() {
  try {
    const resp = await API.get('/auth/me/');
    if (resp.ok) {
      const user = await resp.json();
      const greet = document.getElementById('user-greeting');
      if (greet) greet.textContent = `👋 ${user.full_name || user.email.split('@')[0]}`;

      // Show admin bar if owner/manager
      if (['owner', 'manager', 'superadmin'].includes(user.role)) {
        document.getElementById('admin-bar')?.classList.remove('hidden');
      }
    }
  } catch {}
}

async function logout() {
  try {
    const { refresh } = API.getTokens();
    await API.post('/auth/logout/', { refresh });
  } catch {}
  API.clearTokens();
  updateAuthUI();
  toast('U çkyçet me sukses.');
}

function openAuthModal(tab = 'login') {
  const modal = document.getElementById('auth-modal');
  if (!modal) return;
  modal.classList.remove('hidden');
  switchAuthTab(tab);

  const closeBtn = document.getElementById('close-auth');
  const backdrop = modal.querySelector('.modal-backdrop');
  const closeModal = () => modal.classList.add('hidden');
  closeBtn?.removeEventListener('click', closeModal);
  backdrop?.removeEventListener('click', closeModal);
  closeBtn?.addEventListener('click', closeModal);
  backdrop?.addEventListener('click', closeModal);

  document.getElementById('tab-login')?.addEventListener('click', () => switchAuthTab('login'));
  document.getElementById('tab-register')?.addEventListener('click', () => switchAuthTab('register'));
}

function switchAuthTab(tab) {
  document.querySelectorAll('#auth-tabs .tab-btn').forEach(b => b.classList.toggle('active', b.id === `tab-${tab}`));
  const content = document.getElementById('auth-form-content');
  const errEl = document.getElementById('auth-error');
  if (errEl) errEl.classList.add('hidden');

  if (tab === 'login') {
    content.innerHTML = `
      <input class="form-input" id="auth-email"    type="email"    placeholder="Email" autocomplete="email" />
      <input class="form-input" id="auth-password" type="password" placeholder="Fjalëkalim" autocomplete="current-password" />
      <button class="btn btn-primary btn-block" id="auth-submit" style="margin-top:4px">Hyr</button>
    `;
    document.getElementById('auth-submit').addEventListener('click', doLogin);
    document.getElementById('auth-password').addEventListener('keydown', e => { if(e.key==='Enter') doLogin(); });
  } else {
    content.innerHTML = `
      <input class="form-input" id="auth-name"     type="text"     placeholder="Emri i plotë" autocomplete="name" />
      <input class="form-input" id="auth-email"    type="email"    placeholder="Email" autocomplete="email" />
      <input class="form-input" id="auth-password" type="password" placeholder="Fjalëkalim (min 8 karaktere)" autocomplete="new-password" />
      <button class="btn btn-primary btn-block" id="auth-submit" style="margin-top:4px">Regjistrohu</button>
    `;
    document.getElementById('auth-submit').addEventListener('click', doRegister);
  }
}

async function doLogin() {
  const email    = document.getElementById('auth-email')?.value.trim();
  const password = document.getElementById('auth-password')?.value;
  const errEl    = document.getElementById('auth-error');
  const btn      = document.getElementById('auth-submit');
  btn.disabled = true; btn.textContent = 'Duke u kyçur...';
  try {
    const resp = await API.post('/auth/login/', { email, password });
    const data = await resp.json();
    if (!resp.ok) {
      if (errEl) { errEl.textContent = data.detail || 'Email ose fjalëkalim i gabuar.'; errEl.classList.remove('hidden'); }
      return;
    }
    API.saveTokens(data.access, data.refresh);
    document.getElementById('auth-modal')?.classList.add('hidden');
    updateAuthUI();
    toast('Mirë se vini! ✓');
  } catch { if (errEl) { errEl.textContent = 'Gabim rrjeti.'; errEl.classList.remove('hidden'); } }
  finally { btn.disabled = false; btn.textContent = 'Hyr'; }
}

async function doRegister() {
  const full_name = document.getElementById('auth-name')?.value.trim();
  const email     = document.getElementById('auth-email')?.value.trim();
  const password  = document.getElementById('auth-password')?.value;
  const errEl     = document.getElementById('auth-error');
  const btn       = document.getElementById('auth-submit');
  btn.disabled = true; btn.textContent = 'Duke u regjistruar...';
  try {
    const resp = await API.post('/auth/register/', { full_name, email, password });
    const data = await resp.json();
    if (!resp.ok) {
      if (errEl) { errEl.textContent = Object.values(data).flat().join(' '); errEl.classList.remove('hidden'); }
      return;
    }
    // Auto-login
    const loginResp = await API.post('/auth/login/', { email, password });
    const loginData = await loginResp.json();
    if (loginResp.ok) {
      API.saveTokens(loginData.access, loginData.refresh);
      document.getElementById('auth-modal')?.classList.add('hidden');
      updateAuthUI();
      toast('Llogaria u krijua! Mirë se vini ✓');
    }
  } catch { if (errEl) { errEl.textContent = 'Gabim rrjeti.'; errEl.classList.remove('hidden'); } }
  finally { btn.disabled = false; btn.textContent = 'Regjistrohu'; }
}

// ── Listings / Services ───────────────────────────────────────
async function loadListings() {
  const grid = document.getElementById('listings-grid');
  if (!grid) return;

  const t = window.__BIZAL_TENANT__;
  if (!t) {
    grid.innerHTML = '<div class="loader"><p>Nuk u gjet informacioni i biznesit.</p></div>';
    return;
  }

  // Food businesses → redirect to menu
  if (['restaurant', 'bar', 'bakery', 'delivery_kitchen'].includes(t.business_type)) {
    loadedSections.delete('services'); // allow reload
    showSection('menu');
    return;
  }

  grid.innerHTML = `<div class="loader"><div class="spinner"></div><p>Duke ngarkuar shërbimet...</p></div>`;

  // Update section title
  const titleMap = {
    car_rental: 'Flota Jonë', property_rental: 'Pronat Tona',
    equipment_rental: 'Pajisjet me Qira', boat_rental: 'Barka me Qira',
    clinic: 'Shërbimet Mjekësore', barbershop: 'Shërbimet Tona',
    spa: 'Shërbimet Spa', gym: 'Programet Tona',
    market: 'Produktet Tona', pharmacy: 'Produktet',
  };
  const titleEl = document.getElementById('services-title');
  if (titleEl) titleEl.textContent = titleMap[t.business_type] || 'Shërbimet Tona';

  // Choose endpoint
  const isRental = ['car_rental', 'property_rental', 'equipment_rental', 'boat_rental'].includes(t.business_type);
  const isAppointment = ['clinic', 'barbershop', 'spa', 'gym', 'tattoo', 'auto_repair',
    'lawyer', 'language_school', 'tutoring', 'driving_school', 'coding_bootcamp'].includes(t.business_type);

  let endpoint = '/inventory/';
  let renderFn = renderProduct;
  if (isRental) { endpoint = '/rentals/'; renderFn = renderRentalItem; }
  else if (isAppointment) { endpoint = '/appointments/services/'; renderFn = renderService; }

  // Show search for pro+
  if (t.plan !== 'starter') {
    document.getElementById('search-bar')?.classList.remove('hidden');
    initSearch();
  }

  try {
    const resp = await API.get(endpoint);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    const items = Array.isArray(data) ? data : (data.results || []);

    if (!items.length) {
      grid.innerHTML = `<div class="empty-state"><div class="empty-state-icon">📦</div><h3>Nuk ka shërbime aktualisht</h3><p>Kontrolloni përsëri së shpejti.</p></div>`;
      return;
    }

    grid.innerHTML = items.map(item => renderFn(item)).join('');

    // Bind book buttons
    grid.querySelectorAll('[data-book]').forEach(btn => {
      btn.addEventListener('click', () => {
        const card = btn.closest('[data-item-id]');
        if (card) openBookingModal(JSON.parse(card.dataset.itemJson || '{}'));
      });
    });

  } catch (err) {
    console.error('loadListings error:', err);
    grid.innerHTML = `<div class="empty-state"><div class="empty-state-icon">⚠️</div><h3>Gabim në ngarkimin e të dhënave</h3><p>Ju lutemi provoni përsëri.</p></div>`;
  }
}

function renderService(item) {
  const available = item.is_active !== false;
  return `
    <div class="service-card" data-item-id="${item.id}" data-item-json='${JSON.stringify({id:item.id,name:item.name,price:item.price,type:'appointment'})}'>
      ${item.image ? `<img class="service-card-img" src="${item.image}" alt="${item.name}" loading="lazy" />` : `<div class="service-card-img" style="display:flex;align-items:center;justify-content:center;font-size:3rem">✨</div>`}
      <div class="service-card-body">
        <div class="service-card-name">${item.name}</div>
        <div class="service-card-desc">${item.description || ''}</div>
        <div class="service-card-footer">
          <div class="service-card-price">${item.price ? formatPrice(item.price) : 'Me marrëveshje'}</div>
          ${available
            ? `<button class="btn btn-primary btn-sm" data-book="1">Rezervo</button>`
            : `<span class="service-card-badge unavailable">Pa disponibilitet</span>`}
        </div>
      </div>
    </div>`;
}

function renderRentalItem(item) {
  const available = item.is_available !== false;
  return `
    <div class="service-card" data-item-id="${item.id}" data-item-json='${JSON.stringify({id:item.id,name:item.name||item.make,price:item.daily_rate||item.price_per_day,type:'rental'})}'>
      ${item.image || item.image_url ? `<img class="service-card-img" src="${item.image||item.image_url}" alt="${item.name||item.make}" loading="lazy" />` : `<div class="service-card-img" style="display:flex;align-items:center;justify-content:center;font-size:3rem">🚗</div>`}
      <div class="service-card-body">
        <div class="service-card-name">${item.make ? `${item.make} ${item.model||''} ${item.year||''}`.trim() : item.name}</div>
        <div class="service-card-desc">${item.description || ''}</div>
        <div class="service-card-footer">
          <div class="service-card-price">${formatPrice(item.daily_rate || item.price_per_day)}<small style="font-size:12px;font-weight:400;color:var(--text-muted)">/ditë</small></div>
          ${available
            ? `<button class="btn btn-primary btn-sm" data-book="1">Rezervo</button>`
            : `<span class="service-card-badge unavailable">I zënë</span>`}
        </div>
      </div>
    </div>`;
}

function renderProduct(item) {
  const inStock = item.stock_quantity === undefined || item.stock_quantity > 0;
  return `
    <div class="service-card" data-item-id="${item.id}" data-item-json='${JSON.stringify({id:item.id,name:item.name,price:item.price,type:'product'})}'>
      ${item.image || item.image_url ? `<img class="service-card-img" src="${item.image||item.image_url}" alt="${item.name}" loading="lazy" />` : `<div class="service-card-img" style="display:flex;align-items:center;justify-content:center;font-size:3rem">🛍️</div>`}
      <div class="service-card-body">
        <div class="service-card-name">${item.name}</div>
        <div class="service-card-desc">${item.description || ''}</div>
        <div class="service-card-footer">
          <div class="service-card-price">${formatPrice(item.price)}</div>
          ${inStock
            ? `<span class="service-card-badge available">Në Stock</span>`
            : `<span class="service-card-badge unavailable">Shteruar</span>`}
        </div>
      </div>
    </div>`;
}

// ── Search ────────────────────────────────────────────────────
function initSearch() {
  let searchTimer;
  const input = document.getElementById('search-input');
  input?.addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      loadedSections.delete('services'); // allow reload with new query
      loadListings();
    }, 400);
  });
}

// ── Menu ──────────────────────────────────────────────────────
async function loadMenu() {
  const container = document.getElementById('menu-categories');
  if (!container) return;
  container.innerHTML = '<div class="loader"><div class="spinner"></div><p>Duke ngarkuar menunë...</p></div>';
  try {
    const resp = await API.get('/menu/');
    if (!resp.ok) throw new Error();
    const data = await resp.json();
    const categories = Array.isArray(data) ? data : (data.results || []);
    if (!categories.length) {
      container.innerHTML = '<div class="empty-state"><div class="empty-state-icon">🍽️</div><h3>Menu nuk është konfiguruar ende</h3><p>Kontrolloni përsëri së shpejti.</p></div>';
      return;
    }
    container.innerHTML = categories.map(cat => `
      <div class="menu-category">
        <h3>${cat.name}</h3>
        ${cat.description ? `<p style="color:var(--text-muted);font-size:14px;margin-bottom:18px">${cat.description}</p>` : ''}
        <div class="menu-items">
          ${(cat.items || []).filter(i => i.is_available !== false).map(item => `
            <div class="menu-item">
              <div class="menu-item-info">
                <div class="menu-item-name">${item.name}</div>
                ${item.description ? `<div class="menu-item-desc">${item.description}</div>` : ''}
                ${item.allergens ? `<div style="font-size:11px;color:var(--text-muted);margin-bottom:6px">⚠ ${item.allergens}</div>` : ''}
                <div class="menu-item-price">${formatPrice(item.price)}</div>
              </div>
              ${item.image ? `<img class="menu-item-img" src="${item.image}" alt="${item.name}" loading="lazy" />` : ''}
            </div>`).join('')}
        </div>
      </div>`).join('');
  } catch {
    container.innerHTML = '<div class="empty-state"><div class="empty-state-icon">⚠️</div><h3>Gabim në ngarkimin e menusë</h3></div>';
  }
}

// ── Reviews ───────────────────────────────────────────────────
async function loadReviews() {
  const grid = document.getElementById('reviews-grid');
  const summary = document.getElementById('reviews-summary');
  if (!grid) return;
  grid.innerHTML = '<div class="loader"><div class="spinner"></div><p>Duke ngarkuar vlerësimet...</p></div>';
  try {
    const resp = await API.get('/reviews/');
    if (!resp.ok) throw new Error();
    const data = await resp.json();
    const reviews = Array.isArray(data) ? data : (data.results || []);

    if (!reviews.length) {
      grid.innerHTML = '<div class="empty-state" style="grid-column:1/-1"><div class="empty-state-icon">⭐</div><h3>Nuk ka vlerësime ende</h3><p>Jini i pari që lini një vlerësim!</p></div>';
      return;
    }

    const avg = (reviews.reduce((s, r) => s + r.rating, 0) / reviews.length).toFixed(1);
    if (summary) {
      summary.innerHTML = `
        <div class="avg-rating">${avg}</div>
        <div>
          <div style="color:var(--accent);font-size:24px">${starHTML(Math.round(avg))}</div>
          <div style="color:var(--text-muted);font-size:14px;margin-top:4px">${reviews.length} vlerësime</div>
        </div>`;
      summary.classList.remove('hidden');
    }

    grid.innerHTML = reviews.map(r => `
      <div class="review-card">
        <div class="review-stars">${starHTML(r.rating)}</div>
        <p class="review-comment">${r.comment}</p>
        <div class="review-author">${r.user_name || 'Klient'} <span style="color:var(--text-muted);font-weight:400">· ${formatDate(r.created_at)}</span></div>
      </div>`).join('');
  } catch {
    grid.innerHTML = '<div class="empty-state" style="grid-column:1/-1"><div class="empty-state-icon">⚠️</div><h3>Gabim në ngarkimin e vlerësimeve</h3></div>';
  }
}

function initReviewForm() {
  const stars = document.querySelectorAll('#star-picker .star');
  stars.forEach(star => {
    star.addEventListener('click', () => {
      reviewRating = parseInt(star.dataset.value);
      stars.forEach(s => s.classList.toggle('active', parseInt(s.dataset.value) <= reviewRating));
    });
    star.addEventListener('mouseover', () => {
      const val = parseInt(star.dataset.value);
      stars.forEach(s => s.classList.toggle('active', parseInt(s.dataset.value) <= val));
    });
    star.addEventListener('mouseout', () => {
      stars.forEach(s => s.classList.toggle('active', parseInt(s.dataset.value) <= reviewRating));
    });
  });

  document.getElementById('submit-review')?.addEventListener('click', async () => {
    const comment = document.getElementById('review-comment')?.value.trim();
    if (!reviewRating) { toast('Zgjidhni numrin e yjeve.', 'error'); return; }
    if (!comment) { toast('Shkruani një koment.', 'error'); return; }
    const resp = await API.post('/reviews/', { rating: reviewRating, comment, review_type: 'business' });
    if (resp.ok) {
      document.getElementById('review-comment').value = '';
      reviewRating = 0;
      stars.forEach(s => s.classList.remove('active'));
      toast('Faleminderit për vlerësimin tuaj! ✓');
      loadedSections.delete('reviews');
      loadReviews();
    } else {
      const err = await resp.json().catch(() => ({}));
      toast(Object.values(err).flat().join(' ') || 'Gabim. Provoni përsëri.', 'error');
    }
  });
}

// ── Blog ──────────────────────────────────────────────────────
async function loadBlog() {
  const grid = document.getElementById('blog-grid');
  if (!grid) return;
  grid.innerHTML = '<div class="loader"><div class="spinner"></div></div>';
  try {
    const resp = await API.get('/blog/');
    if (!resp.ok) throw new Error();
    const data = await resp.json();
    const posts = Array.isArray(data) ? data : (data.results || []);
    if (!posts.length) {
      grid.innerHTML = '<div class="empty-state" style="grid-column:1/-1"><div class="empty-state-icon">📰</div><h3>Nuk ka artikuj ende</h3></div>';
      return;
    }
    grid.innerHTML = posts.map(p => `
      <div class="blog-card" data-slug="${p.slug}">
        ${p.cover_url ? `<img class="blog-card-img" src="${p.cover_url}" alt="${p.title}" loading="lazy" />` : ''}
        <div class="blog-card-body">
          <div class="blog-card-title">${p.title}</div>
          <div class="blog-card-excerpt">${p.excerpt || ''}</div>
          <div style="font-size:12px;color:var(--text-muted);margin-top:12px">${formatDate(p.published_at)}</div>
        </div>
      </div>`).join('');
    grid.querySelectorAll('.blog-card').forEach(card => {
      card.addEventListener('click', () => openBlogPost(card.dataset.slug));
    });
  } catch {
    grid.innerHTML = '<div class="empty-state" style="grid-column:1/-1"><div class="empty-state-icon">⚠️</div><h3>Gabim në ngarkimin e blogut</h3></div>';
  }
}

async function openBlogPost(slug) {
  const resp = await API.get(`/blog/${slug}/`);
  if (!resp.ok) { toast('Artikulli nuk u gjet.', 'error'); return; }
  const post = await resp.json();
  const modal = document.createElement('div');
  modal.className = 'modal';
  modal.innerHTML = `
    <div class="modal-backdrop"></div>
    <div class="modal-box" style="max-width:700px">
      <button class="modal-close" id="close-blog-post">✕</button>
      ${post.cover_url ? `<img src="${post.cover_url}" style="width:100%;border-radius:8px;margin-bottom:24px" alt="${post.title}" />` : ''}
      <h2 style="margin-bottom:8px">${post.title}</h2>
      <div style="font-size:13px;color:var(--text-muted);margin-bottom:24px">${formatDate(post.published_at)} · ${post.author_name||''}</div>
      <div style="line-height:1.8;font-size:15px">${post.body}</div>
    </div>`;
  document.body.appendChild(modal);
  modal.querySelector('.modal-backdrop').addEventListener('click', () => modal.remove());
  modal.querySelector('#close-blog-post').addEventListener('click', () => modal.remove());
}

// ── Contact ───────────────────────────────────────────────────
function loadContactInfo() {
  const t = window.__BIZAL_TENANT__;
  const infoEl = document.getElementById('contact-info');
  if (!infoEl || !t) return;
  let html = '';
  if (t.address || t.city) html += `<div class="contact-info-item">📍 ${[t.address, t.city].filter(Boolean).join(', ')}</div>`;
  if (t.phone)   html += `<div class="contact-info-item"><a href="tel:${t.phone}" style="color:inherit;text-decoration:none">📞 ${t.phone}</a></div>`;
  if (t.email)   html += `<div class="contact-info-item"><a href="mailto:${t.email}" style="color:inherit;text-decoration:none">✉️ ${t.email}</a></div>`;
  infoEl.innerHTML = html;
}

function initContact() {
  document.getElementById('send-contact')?.addEventListener('click', async () => {
    const name    = document.getElementById('contact-name')?.value.trim();
    const email   = document.getElementById('contact-email')?.value.trim();
    const phone   = document.getElementById('contact-phone')?.value.trim();
    const subject = document.getElementById('contact-subject')?.value.trim();
    const message = document.getElementById('contact-message')?.value.trim();
    const fb = document.getElementById('contact-feedback');
    if (!name || !email || !message) { showFeedback(fb, 'Emri, emaili dhe mesazhi janë të detyrueshme.', 'error'); return; }
    const btn = document.getElementById('send-contact');
    btn.disabled = true; btn.textContent = 'Duke dërguar...';
    try {
      const resp = await API.post('/contact/', { name, email, phone, subject, message });
      if (resp.ok) {
        showFeedback(fb, '✓ Mesazhi u dërgua! Do ju kthehemi së shpejti.', 'success');
        ['contact-name','contact-email','contact-phone','contact-subject','contact-message'].forEach(id => {
          const el = document.getElementById(id); if (el) el.value = '';
        });
      } else {
        showFeedback(fb, 'Gabim në dërgim. Provoni përsëri.', 'error');
      }
    } catch { showFeedback(fb, 'Gabim rrjeti.', 'error'); }
    finally { btn.disabled = false; btn.textContent = 'Dërgo Mesazhin'; }
  });
}

// ── Booking Modal ─────────────────────────────────────────────
function openBookingModal(item) {
  if (!API.isLoggedIn()) {
    openAuthModal('login');
    toast('Kyçuni për të bërë një rezervim.', 'warning');
    return;
  }
  const modal = document.getElementById('booking-modal');
  const title = document.getElementById('booking-modal-title');
  const content = document.getElementById('booking-form-content');
  if (!modal || !content) return;

  title.textContent = `Rezervo: ${item.name}`;
  const isRental = item.type === 'rental';

  content.innerHTML = `
    <div class="booking-form">
      <label class="form-label">Emri i plotë *</label>
      <input id="bk-name" type="text" placeholder="Emri juaj" />
      <label class="form-label">Email *</label>
      <input id="bk-email" type="email" placeholder="email@example.com" />
      <label class="form-label">Telefon</label>
      <input id="bk-phone" type="tel" placeholder="+355..." />
      ${isRental ? `
        <label class="form-label">Data e nisjes *</label>
        <input id="bk-start" type="date" min="${new Date().toISOString().split('T')[0]}" />
        <label class="form-label">Data e kthimit *</label>
        <input id="bk-end" type="date" />
      ` : `
        <label class="form-label">Data *</label>
        <input id="bk-date" type="date" min="${new Date().toISOString().split('T')[0]}" />
        <label class="form-label">Ora *</label>
        <input id="bk-time" type="time" />
      `}
      <label class="form-label">Shënime</label>
      <textarea id="bk-notes" rows="3" placeholder="Kërkesat tuaja speciale..."></textarea>
      <div id="bk-price-summary" class="price-summary" style="display:none"></div>
      <div id="bk-feedback" class="feedback hidden" style="margin-bottom:12px"></div>
      <button class="btn btn-primary btn-block" id="bk-submit">Dërgo Rezervimin</button>
    </div>`;

  // Live price calculation for rentals
  if (isRental && item.price) {
    const calcPrice = () => {
      const start = document.getElementById('bk-start')?.value;
      const end   = document.getElementById('bk-end')?.value;
      if (start && end) {
        const days = Math.max(1, Math.round((new Date(end) - new Date(start)) / 86400000));
        const total = days * parseFloat(item.price);
        const ps = document.getElementById('bk-price-summary');
        ps.style.display = 'block';
        ps.innerHTML = `
          <div class="price-row"><span>${days} ditë × ${formatPrice(item.price)}</span></div>
          <div class="price-row total"><span>Total</span><span>${formatPrice(total)}</span></div>`;
      }
    };
    document.getElementById('bk-start')?.addEventListener('change', calcPrice);
    document.getElementById('bk-end')?.addEventListener('change', calcPrice);
  }

  document.getElementById('bk-submit')?.addEventListener('click', async () => {
    const guestName  = document.getElementById('bk-name')?.value.trim();
    const guestEmail = document.getElementById('bk-email')?.value.trim();
    const notes      = document.getElementById('bk-notes')?.value.trim();
    const feedback   = document.getElementById('bk-feedback');

    if (!guestName || !guestEmail) { showFeedback(feedback, 'Emri dhe emaili janë të detyrueshme.', 'error'); return; }

    let body = { guest_name: guestName, guest_email: guestEmail, notes };
    if (isRental) {
      const start = document.getElementById('bk-start')?.value;
      const end   = document.getElementById('bk-end')?.value;
      if (!start || !end) { showFeedback(feedback, 'Zgjidhni datat.', 'error'); return; }
      const days = Math.max(1, Math.round((new Date(end) - new Date(start)) / 86400000));
      body = { ...body, booking_type: 'rental', start_date: start, end_date: end, resource_id: item.id, resource_type: 'rental_item', resource_label: item.name, total_price: days * parseFloat(item.price||0) };
    } else {
      const date = document.getElementById('bk-date')?.value;
      const time = document.getElementById('bk-time')?.value;
      if (!date || !time) { showFeedback(feedback, 'Zgjidhni datën dhe orën.', 'error'); return; }
      body = { ...body, booking_type: 'appointment', start_date: date, start_time: time, resource_id: item.id, resource_label: item.name, total_price: item.price||0 };
    }

    const btn = document.getElementById('bk-submit');
    btn.disabled = true; btn.textContent = 'Duke dërguar...';
    try {
      const resp = await API.post('/bookings/', body);
      if (resp.ok) {
        modal.classList.add('hidden');
        toast('Rezervimi u dërgua me sukses! Do ju kontaktojmë. ✓');
      } else {
        const err = await resp.json().catch(() => ({}));
        showFeedback(feedback, Object.values(err).flat().join(' ') || 'Gabim. Provoni përsëri.', 'error');
      }
    } catch { showFeedback(feedback, 'Gabim rrjeti.', 'error'); }
    finally { btn.disabled = false; btn.textContent = 'Dërgo Rezervimin'; }
  });

  modal.classList.remove('hidden');
  document.getElementById('close-booking')?.addEventListener('click', () => modal.classList.add('hidden'));
  modal.querySelector('.modal-backdrop')?.addEventListener('click', () => modal.classList.add('hidden'));
}

// ── Tenant Ready ──────────────────────────────────────────────
function onTenantReady(t) {
  tenant = t;

  // Show the hero
  document.getElementById('section-home')?.classList.remove('hidden');

  initNav();
  updateAuthUI();
  initReviewForm();
  initContact();

  // Route to the right section based on current URL hash
  const section = getSectionFromHash();
  showSection(section, false);
}

window.addEventListener('tenantReady', (e) => onTenantReady(e.detail));

// Fallback if tenant.js already fired (cached)
if (window.__BIZAL_TENANT__) {
  onTenantReady(window.__BIZAL_TENANT__);
}
