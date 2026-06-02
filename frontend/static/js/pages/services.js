/* services.js — Services / Listings Page */
const { API, show, hide, formatPrice, formatDate, showFeedback, toast } = window.BizAL;

let allItems = [];
let currentPage = 1;
const PER_PAGE = 9;
let activeFilter = '';
let bookingRating = 0;

// ---- Route to correct endpoint by business type ----
function getConfig(t) {
  const type = t.business_type;
  if (['restaurant','bar','bakery','delivery_kitchen'].includes(type)) {
    return { endpoint: '/menu/', render: renderMenuFull, heading: 'Menu', subheading: 'Të gjitha pjatat dhe produktet tona', isMenu: true };
  }
  if (['car_rental','property_rental','equipment_rental','boat_rental'].includes(type)) {
    return { endpoint: '/rentals/', render: renderRental, heading: 'Disponueshme', subheading: 'Zgjidhni dhe rezervoni online' };
  }
  if (['clinic','barbershop','spa','gym','tattoo','auto_repair','lawyer','language_school','tutoring','driving_school'].includes(type)) {
    return { endpoint: '/appointments/services/', render: renderService, heading: 'Shërbimet Tona', subheading: 'Rezervoni takimin tuaj online' };
  }
  return { endpoint: '/inventory/', render: renderProduct, heading: 'Produktet Tona', subheading: 'Gjeni produktin e duhur' };
}

// ---- Load ----
async function loadListings() {
  const t = window.__BIZAL_TENANT__;
  if (!t) return;
  const cfg = getConfig(t);

  document.getElementById('page-heading').textContent = cfg.heading;
  document.getElementById('page-subheading').textContent = cfg.subheading;

  const grid = document.getElementById('listings-grid');
  grid.innerHTML = '<div class="skeleton-card"></div>'.repeat(6);

  const search = document.getElementById('search-input')?.value.trim() || '';
  let url = cfg.endpoint;
  if (search) url += `?search=${encodeURIComponent(search)}`;
  if (activeFilter) url += `${search ? '&' : '?'}type=${encodeURIComponent(activeFilter)}`;

  const resp = await API.get(url);
  if (!resp.ok) { grid.innerHTML = '<p class="text-muted" style="text-align:center;padding:60px;grid-column:1/-1">Gabim në ngarkimin e të dhënave.</p>'; return; }
  const data = await resp.json();
  allItems = data.results || data;

  renderPage(cfg, 1);
  buildFilters(t);
}

function renderPage(cfg, page) {
  currentPage = page;
  const grid = document.getElementById('listings-grid');
  const meta = document.getElementById('results-meta');
  const start = (page - 1) * PER_PAGE;
  const items = allItems.slice(start, start + PER_PAGE);

  if (meta) meta.textContent = `${allItems.length} shërbime`;

  if (!allItems.length) {
    grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:80px;color:var(--text-muted)"><div style="font-size:3rem;margin-bottom:12px">🔍</div><p>Nuk u gjet asgjë.</p></div>';
    renderPagination(0);
    return;
  }

  if (cfg.isMenu) {
    grid.style.gridTemplateColumns = '1fr';
    grid.innerHTML = allItems.map(cfg.render).join('');
  } else {
    grid.style.gridTemplateColumns = '';
    grid.innerHTML = items.map(cfg.render).join('');
  }

  grid.querySelectorAll('.book-btn').forEach(btn => {
    btn.addEventListener('click', () => openBookingModal(btn.dataset));
  });

  renderPagination(allItems.length);
}

function renderPagination(total) {
  const el = document.getElementById('pagination');
  if (!el) return;
  const pages = Math.ceil(total / PER_PAGE);
  if (pages <= 1) { el.innerHTML = ''; return; }
  const t = window.__BIZAL_TENANT__;
  const cfg = getConfig(t);
  el.innerHTML = Array.from({ length: pages }, (_, i) => i + 1).map(p => `
    <button class="page-btn ${p === currentPage ? 'active' : ''}" data-p="${p}">${p}</button>
  `).join('');
  el.querySelectorAll('.page-btn').forEach(btn => {
    btn.addEventListener('click', () => renderPage(cfg, parseInt(btn.dataset.p)));
  });
}

// ---- Render functions ----
function renderRental(item) {
  const icons = { car: '🚗', boat: '⛵', property: '🏠', equipment: '🔧' };
  return `<div class="card">
    ${item.image ? `<img class="card-image" src="${item.image}" alt="${item.name}" loading="lazy" />` : `<div class="card-image-placeholder">${icons[item.rental_type] || '🚗'}</div>`}
    <div class="card-body">
      ${item.city ? `<span class="card-badge">📍 ${item.city}</span>` : ''}
      <div class="card-title">${item.name}</div>
      <div class="card-desc">${item.description || Object.entries(item.specs || {}).map(([k,v]) => `${k}: ${v}`).join(' · ') || ''}</div>
      <div class="card-footer">
        <div><div class="card-price">${formatPrice(item.price_per_day)}</div><div class="card-price-sub">/ ditë</div></div>
        <button class="btn btn-primary btn-sm book-btn"
          data-id="${item.id}" data-name="${item.name}"
          data-price="${item.price_per_day}" data-type="rental">
          Rezervo
        </button>
      </div>
    </div>
  </div>`;
}

function renderService(item) {
  return `<div class="card">
    <div class="card-image-placeholder">✂️</div>
    <div class="card-body">
      <span class="card-badge">⏱ ${item.duration_minutes} min</span>
      <div class="card-title">${item.name}</div>
      <div class="card-desc">${item.description || ''}</div>
      <div class="card-footer">
        <div class="card-price">${formatPrice(item.price)}</div>
        <button class="btn btn-primary btn-sm book-btn"
          data-id="${item.id}" data-name="${item.name}"
          data-price="${item.price}" data-type="appointment">
          Takim
        </button>
      </div>
    </div>
  </div>`;
}

function renderProduct(item) {
  return `<div class="card">
    ${item.image ? `<img class="card-image" src="${item.image}" alt="${item.name}" loading="lazy" />` : '<div class="card-image-placeholder">🛍️</div>'}
    <div class="card-body">
      ${item.category_name ? `<span class="card-badge">${item.category_name}</span>` : ''}
      <div class="card-title">${item.name}</div>
      <div class="card-desc">${item.description || ''}</div>
      <div class="card-footer">
        <div class="card-price">${formatPrice(item.price)}</div>
        <span style="font-size:12px;color:${item.in_stock ? 'var(--success)' : 'var(--danger)'};font-weight:600">
          ${item.in_stock ? '✓ Në gjendje' : '✗ I shteruar'}
        </span>
      </div>
    </div>
  </div>`;
}

function renderMenuFull(cat) {
  if (!cat.items || !cat.items.length) return '';
  return `<div style="margin-bottom:48px">
    <h2 style="font-size:1.4rem;font-weight:800;margin-bottom:20px;padding-bottom:10px;border-bottom:2px solid var(--primary)">${cat.name}</h2>
    <div class="grid">
      ${cat.items.filter(i => i.is_available).map(item => `
        <div class="card" style="flex-direction:row;align-items:center;gap:0;padding:0">
          ${item.image ? `<img src="${item.image}" alt="${item.name}" style="width:100px;height:100px;object-fit:cover;border-radius:var(--radius) 0 0 var(--radius);flex-shrink:0" loading="lazy" />` : ''}
          <div class="card-body" style="padding:16px">
            <div class="card-title" style="margin-bottom:4px">${item.name}</div>
            ${item.description ? `<div class="card-desc" style="font-size:13px;margin-bottom:8px">${item.description}</div>` : ''}
            ${item.allergens ? `<div style="font-size:11px;color:var(--text-muted);margin-bottom:8px">⚠ ${item.allergens}</div>` : ''}
            <div style="font-size:1.1rem;font-weight:800;color:var(--primary)">${formatPrice(item.price)}</div>
          </div>
        </div>`).join('')}
    </div>
  </div>`;
}

// ---- Filters ----
function buildFilters(t) {
  const chips = document.getElementById('filter-chips');
  if (!chips) return;
  const type = t.business_type;
  let labels = [];
  if (['car_rental','boat_rental','property_rental','equipment_rental'].includes(type)) {
    labels = [['car','Makina'],['property','Prona'],['boat','Barka'],['equipment','Pajisje']];
  }
  if (!labels.length) { chips.innerHTML = ''; return; }

  chips.innerHTML = `<button class="chip active" data-filter="">Të gjitha</button>` +
    labels.map(([v, l]) => `<button class="chip" data-filter="${v}">${l}</button>`).join('');
  chips.querySelectorAll('.chip').forEach(chip => {
    chip.addEventListener('click', () => {
      chips.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
      chip.classList.add('active');
      activeFilter = chip.dataset.filter;
      loadListings();
    });
  });
}

// ---- Booking Modal ----
function openBookingModal({ id, name, price, type }) {
  const modal = document.getElementById('booking-modal');
  const title = document.getElementById('booking-modal-title');
  const content = document.getElementById('booking-form-content');
  if (!modal) return;
  title.textContent = `Rezervo: ${name}`;

  if (type === 'rental') {
    content.innerHTML = `
      <div>
        <div class="booking-form-row" style="margin-bottom:12px">
          <div class="form-group"><label class="form-label">Data e fillimit</label>
            <input class="form-input" type="date" id="bk-start" min="${new Date().toISOString().split('T')[0]}" /></div>
          <div class="form-group"><label class="form-label">Data e mbarimit</label>
            <input class="form-input" type="date" id="bk-end" min="${new Date().toISOString().split('T')[0]}" /></div>
        </div>
        <div class="price-summary" id="bk-price-summary" style="display:none">
          <div class="price-row"><span>Çmimi/ditë</span><span>${formatPrice(price)}</span></div>
          <div class="price-row"><span>Ditë</span><span id="bk-days">-</span></div>
          <div class="price-row total"><span>Totali</span><span id="bk-total">-</span></div>
        </div>
        <div class="booking-form-row" style="margin-bottom:12px">
          <div class="form-group"><label class="form-label">Emri juaj *</label>
            <input class="form-input" type="text" id="bk-name" placeholder="Emri i plotë" /></div>
          <div class="form-group"><label class="form-label">Email *</label>
            <input class="form-input" type="email" id="bk-email" placeholder="email@juaj.al" /></div>
        </div>
        <div class="form-group" style="margin-bottom:12px"><label class="form-label">Telefon</label>
          <input class="form-input" type="tel" id="bk-phone" placeholder="+355..." /></div>
        <div class="form-group" style="margin-bottom:16px"><label class="form-label">Shënime</label>
          <textarea class="form-input" id="bk-notes" rows="2" placeholder="Opsional..."></textarea></div>
        <button class="btn btn-primary btn-block btn-lg" id="bk-submit">Konfirmo Rezervimin</button>
        <div id="bk-feedback" class="feedback hidden" style="margin-top:12px"></div>
      </div>`;
    initDateCalc(price);
  } else {
    content.innerHTML = `
      <div>
        <div class="booking-form-row" style="margin-bottom:12px">
          <div class="form-group"><label class="form-label">Data *</label>
            <input class="form-input" type="date" id="bk-date" min="${new Date().toISOString().split('T')[0]}" /></div>
          <div class="form-group"><label class="form-label">Ora *</label>
            <input class="form-input" type="time" id="bk-time" /></div>
        </div>
        <div class="booking-form-row" style="margin-bottom:12px">
          <div class="form-group"><label class="form-label">Emri juaj *</label>
            <input class="form-input" type="text" id="bk-name" /></div>
          <div class="form-group"><label class="form-label">Email *</label>
            <input class="form-input" type="email" id="bk-email" /></div>
        </div>
        <div class="form-group" style="margin-bottom:12px"><label class="form-label">Telefon</label>
          <input class="form-input" type="tel" id="bk-phone" /></div>
        <div class="form-group" style="margin-bottom:16px"><label class="form-label">Shënime</label>
          <textarea class="form-input" id="bk-notes" rows="2" placeholder="Opsional..."></textarea></div>
        <button class="btn btn-primary btn-block btn-lg" id="bk-submit">Konfirmo Takimin</button>
        <div id="bk-feedback" class="feedback hidden" style="margin-top:12px"></div>
      </div>`;
  }

  show(modal);
  document.getElementById('close-booking')?.addEventListener('click', () => hide(modal));
  modal.querySelector('.modal-backdrop')?.addEventListener('click', () => hide(modal));
  document.getElementById('bk-submit')?.addEventListener('click', () => submitBooking(id, type, price, name));
}

function initDateCalc(pricePerDay) {
  const update = () => {
    const s = document.getElementById('bk-start')?.value;
    const e = document.getElementById('bk-end')?.value;
    const summary = document.getElementById('bk-price-summary');
    if (s && e && e > s) {
      const days = Math.ceil((new Date(e) - new Date(s)) / 86400000);
      document.getElementById('bk-days').textContent = days;
      document.getElementById('bk-total').textContent = formatPrice(days * parseFloat(pricePerDay));
      summary.style.display = 'block';
    }
  };
  document.getElementById('bk-start')?.addEventListener('change', update);
  document.getElementById('bk-end')?.addEventListener('change', update);
}

async function submitBooking(resourceId, type, price, name) {
  const feedback = document.getElementById('bk-feedback');
  const guestName = document.getElementById('bk-name')?.value.trim();
  const guestEmail = document.getElementById('bk-email')?.value.trim();
  const guestPhone = document.getElementById('bk-phone')?.value.trim();
  const notes = document.getElementById('bk-notes')?.value.trim();

  if (!guestName || !guestEmail) { showFeedback(feedback, 'Emri dhe emaili janë të detyrueshme.', 'error'); return; }

  let body = { guest_name: guestName, guest_email: guestEmail, guest_phone: guestPhone, notes, resource_label: name, resource_id: resourceId };

  if (type === 'rental') {
    const start = document.getElementById('bk-start')?.value;
    const end = document.getElementById('bk-end')?.value;
    if (!start || !end || end <= start) { showFeedback(feedback, 'Zgjidhni datat e vlefshme.', 'error'); return; }
    const days = Math.ceil((new Date(end) - new Date(start)) / 86400000);
    Object.assign(body, { booking_type: 'rental', start_date: start, end_date: end, resource_type: 'rental_item', total_price: days * parseFloat(price) });
  } else {
    const date = document.getElementById('bk-date')?.value;
    const time = document.getElementById('bk-time')?.value;
    if (!date || !time) { showFeedback(feedback, 'Zgjidhni datën dhe orën.', 'error'); return; }
    Object.assign(body, { booking_type: 'appointment', start_date: date, start_time: time, total_price: price });
  }

  const btn = document.getElementById('bk-submit');
  btn.disabled = true; btn.textContent = 'Duke dërguar...';

  const resp = await API.post('/bookings/', body);
  btn.disabled = false; btn.textContent = type === 'rental' ? 'Konfirmo Rezervimin' : 'Konfirmo Takimin';

  if (resp.ok) {
    hide(document.getElementById('booking-modal'));
    toast('Rezervimi u dërgua! Do ju kontaktojmë së shpejti. ✓');
  } else {
    const err = await resp.json();
    showFeedback(feedback, Object.values(err).flat().join(' ') || 'Gabim. Provoni përsëri.', 'error');
  }
}

// ---- Search ----
document.getElementById('search-input')?.addEventListener('input',
  window.BizAL.debounce(loadListings, 400));

// ---- Init ----
window.addEventListener('tenantReady', (e) => { loadListings(); });
if (window.__BIZAL_TENANT__) window.dispatchEvent(new CustomEvent('tenantReady', { detail: window.__BIZAL_TENANT__ }));
