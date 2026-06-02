/* home.js — Tenant Home Page */
const { API, show, hide, starHTML, formatPrice, formatDate, toast } = window.BizAL;

const FEATURES_BY_TYPE = {
  restaurant:    [['🍽️','Cilësi e Lartë','Produkte të freskëta dhe receta tradicionale'],['⚡','Shërbim i Shpejtë','Rezervime online, konfirmim i menjëhershëm'],['❤️','Eksperiencë Unike','Atmosferë e ngrohtë dhe personel i sjellshëm']],
  hotel:         [['🏨','Dhoma Luksoze','Komoditet maksimal për pushimin tuaj'],['📅','Rezervim i Lehtë','Kalendarit live me disponueshmëri në kohë reale'],['🌟','Shërbim 24/7','Ne jemi gjithmonë këtu për çdo nevojë']],
  car_rental:    [['🚗','Flotë Moderne','Makina të reja dhe të mirëmbajtura'],['📍','Dërgim & Marrje','Kudo në qytet, pa kosto shtesë'],['🛡️','E Siguruar','Çdo makinë me sigurim të plotë']],
  clinic:        [['👨‍⚕️','Mjekë Specialistë','Staf i kualifikuar me vite eksperiencë'],['📋','Raporte Dixhitale','Rezultate dhe historik mjekësor online'],['⏰','Takime Fleksibël','Orare të përshtatshme sipas nevojave tuaja']],
  barbershop:    [['✂️','Prerje Profesionale','Stilistë të certifikuar me teknika moderne'],['📱','Rezervim Online','Takimi juaj me një klik, 24/7'],['💈','Produkte Premium','Vetëm produktet më të mira për flokët tuaj']],
  gym:           [['💪','Pajisje Moderne','Sala e re me teknologjinë e fundit'],['🏃','Trainer Personal','Udhëzim profesional për rezultate maksimale'],['🥗','Konsulencë Nutricionale','Plan ushqimor i personalizuar']],
  default:       [['⭐','Cilësi e Garantuar','Shërbim profesional me standarde të larta'],['🤝','Besueshmëri','Vite eksperiencë dhe mijëra klientë të kënaqur'],['📞','Mbështetje 24/7','Gjithmonë të gatshëm për ju']],
};

async function loadServicesPreview() {
  const t = window.__BIZAL_TENANT__;
  if (!t) return;
  const grid = document.getElementById('services-preview');
  if (!grid) return;

  let endpoint = '/inventory/';
  let renderFn = renderProductCard;

  const type = t.business_type;
  if (['restaurant','bar','bakery','delivery_kitchen'].includes(type)) {
    endpoint = '/menu/'; renderFn = renderMenuPreview;
  } else if (['car_rental','property_rental','equipment_rental','boat_rental'].includes(type)) {
    endpoint = '/rentals/?limit=3'; renderFn = renderRentalCard;
  } else if (['clinic','barbershop','spa','gym','tattoo','auto_repair','lawyer','language_school','tutoring','driving_school'].includes(type)) {
    endpoint = '/appointments/services/'; renderFn = renderServiceCard;
  }

  const resp = await API.get(endpoint);
  if (!resp.ok) { grid.innerHTML = '<p class="text-muted">Nuk ka shërbime aktualisht.</p>'; return; }
  const data = await resp.json();
  const items = (data.results || data).slice(0, 3);

  if (!items.length) { grid.innerHTML = '<p class="text-muted" style="text-align:center;padding:40px;grid-column:1/-1">Nuk ka shërbime aktualisht.</p>'; return; }
  grid.innerHTML = items.map(renderFn).join('');
}

function renderRentalCard(item) {
  return `<div class="card">
    <div class="card-image-placeholder">${item.rental_type === 'car' ? '🚗' : item.rental_type === 'boat' ? '⛵' : '🏠'}</div>
    <div class="card-body">
      <span class="card-badge">${item.city || ''}</span>
      <div class="card-title">${item.name}</div>
      <div class="card-desc">${item.description || ''}</div>
      <div class="card-footer">
        <div><div class="card-price">${formatPrice(item.price_per_day)}</div><div class="card-price-sub">/ ditë</div></div>
        <a href="/services/" class="btn btn-primary btn-sm">Rezervo</a>
      </div>
    </div>
  </div>`;
}

function renderServiceCard(item) {
  return `<div class="card">
    <div class="card-image-placeholder">🔧</div>
    <div class="card-body">
      <span class="card-badge">${item.duration_minutes} min</span>
      <div class="card-title">${item.name}</div>
      <div class="card-desc">${item.description || ''}</div>
      <div class="card-footer">
        <div class="card-price">${formatPrice(item.price)}</div>
        <a href="/services/" class="btn btn-primary btn-sm">Takim</a>
      </div>
    </div>
  </div>`;
}

function renderProductCard(item) {
  return `<div class="card">
    ${item.image ? `<img class="card-image" src="${item.image}" alt="${item.name}" loading="lazy" />` : '<div class="card-image-placeholder">🛍️</div>'}
    <div class="card-body">
      <div class="card-title">${item.name}</div>
      <div class="card-desc">${item.description || ''}</div>
      <div class="card-footer">
        <div class="card-price">${formatPrice(item.price)}</div>
        <span style="font-size:12px;color:${item.in_stock ? 'var(--success)' : 'var(--danger)'}">${item.in_stock ? '✓ Në gjendje' : '✗ I shteruar'}</span>
      </div>
    </div>
  </div>`;
}

function renderMenuPreview(cat) {
  if (!cat.items || !cat.items.length) return '';
  const item = cat.items[0];
  return `<div class="card">
    <div class="card-image-placeholder">🍽️</div>
    <div class="card-body">
      <span class="card-badge">${cat.name}</span>
      <div class="card-title">${item.name}</div>
      <div class="card-desc">${item.description || ''}</div>
      <div class="card-footer">
        <div class="card-price">${formatPrice(item.price)}</div>
        <a href="/menu/" class="btn btn-primary btn-sm">Shiko Menu</a>
      </div>
    </div>
  </div>`;
}

async function loadReviewsPreview() {
  const t = window.__BIZAL_TENANT__;
  if (!t || !t.has_reviews) return;
  const section = document.getElementById('reviews-section');
  const grid = document.getElementById('reviews-preview');
  const summary = document.getElementById('reviews-summary');
  if (!section || !grid) return;

  const resp = await API.get('/reviews/?limit=3');
  if (!resp.ok) return;
  const data = await resp.json();
  const reviews = data.results || data;
  if (!reviews.length) return;

  show(section);
  const avg = (reviews.reduce((s, r) => s + r.rating, 0) / reviews.length).toFixed(1);
  summary.innerHTML = `
    <div class="avg-rating-num">${avg}</div>
    <div>
      <div class="avg-stars">${starHTML(Math.round(avg))}</div>
      <div class="avg-count">${reviews.length} vlerësime</div>
    </div>`;
  grid.innerHTML = reviews.map(r => `
    <div class="review-card">
      <div class="review-stars">${starHTML(r.rating)}</div>
      <p class="review-comment">${r.comment}</p>
      <div class="review-author">${r.user_name} <span class="review-date">· ${formatDate(r.created_at)}</span></div>
    </div>`).join('');
}

function buildFeatures(t) {
  const grid = document.getElementById('features-grid');
  if (!grid) return;
  const cards = (FEATURES_BY_TYPE[t.business_type] || FEATURES_BY_TYPE.default);
  grid.innerHTML = cards.map(([icon, title, desc]) => `
    <div class="feature-card">
      <span class="feature-icon">${icon}</span>
      <h3>${title}</h3>
      <p>${desc}</p>
    </div>`).join('');
}

function buildHoursBanner(t) {
  const banner = document.getElementById('hours-banner');
  const list = document.getElementById('hours-list');
  if (!banner || !list || !t.business_hours) return;
  const hours = t.business_hours;
  if (!Object.keys(hours).length) return;
  list.innerHTML = Object.entries(hours).map(([d, h]) => `<span>${d}: ${h}</span>`).join(' &nbsp;·&nbsp; ');
  show(banner);
}

function updateHeroCTA(t) {
  const cta = document.getElementById('hero-cta');
  if (!cta) return;
  const labels = {
    restaurant: 'Shiko Menunë', hotel: 'Shiko Dhomat',
    car_rental: 'Shiko Flotën', clinic: 'Rezervo Takim',
    barbershop: 'Rezervo Takim', gym: 'Shiko Planet',
    default: 'Shiko Shërbimet',
  };
  cta.textContent = labels[t.business_type] || labels.default;
  if (['restaurant','bar','bakery','delivery_kitchen'].includes(t.business_type)) {
    cta.href = '/menu/';
  }
}

window.addEventListener('tenantReady', async (e) => {
  const t = e.detail;
  buildFeatures(t);
  updateHeroCTA(t);
  buildHoursBanner(t);
  await loadServicesPreview();
  await loadReviewsPreview();
});

if (window.__BIZAL_TENANT__) {
  window.dispatchEvent(new CustomEvent('tenantReady', { detail: window.__BIZAL_TENANT__ }));
}
