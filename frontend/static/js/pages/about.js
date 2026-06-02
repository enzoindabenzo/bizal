/* about.js — About Page */
const { API, show, hide } = window.BizAL;

const DAYS_SQ = ['E Diel','E Hënë','E Martë','E Mërkurë','E Enjte','E Premte','E Shtunë'];

function buildInfoCard(t) {
  const items = [];
  if (t.address || t.city) items.push(['📍','Adresa', `${t.address || ''}${t.city ? ', ' + t.city : ''}`]);
  if (t.phone) items.push(['📞','Telefon', `<a href="tel:${t.phone}">${t.phone}</a>`]);
  if (t.email) items.push(['✉️','Email', `<a href="mailto:${t.email}">${t.email}</a>`]);
  if (t.website) items.push(['🌐','Website', `<a href="${t.website}" target="_blank" rel="noopener">${t.website.replace(/^https?:\/\//,'')}</a>`]);

  const el = document.getElementById('info-items');
  if (el) el.innerHTML = items.map(([icon, label, value]) => `
    <div class="info-item">
      <span class="info-icon">${icon}</span>
      <div>
        <div class="info-label">${label}</div>
        <div class="info-value">${value}</div>
      </div>
    </div>`).join('');
}

function buildStory(t) {
  const heading = document.getElementById('story-heading');
  const body = document.getElementById('story-body');
  const badge = document.getElementById('founded-badge');
  const sub = document.getElementById('about-sub');

  if (sub) sub.textContent = t.tagline || '';
  if (badge && t.founded_year) {
    badge.textContent = `Themeluar ${t.founded_year}`;
    show(badge);
  }
  if (heading) heading.textContent = `Historia e ${t.name}`;
  if (body) {
    if (t.story) {
      const filled = t.story
        .replace(/\{name\}/g, t.name)
        .replace(/\{city\}/g, t.city || '')
        .replace(/\{year\}/g, t.founded_year || '');
      body.innerHTML = filled.split('\n').filter(Boolean).map(p => `<p>${p}</p>`).join('');
    } else {
      body.innerHTML = `<p>${t.name} është një biznes i besuar${t.city ? ' në ' + t.city : ''}, i dedikuar ndaj cilësisë dhe kënaqësisë së klientëve.</p>`;
    }
  }
}

function buildHours(t) {
  const section = document.getElementById('hours-section');
  const tbody = document.getElementById('hours-rows');
  if (!tbody || !t.business_hours) return;
  const hours = t.business_hours;
  if (!Object.keys(hours).length) { if (section) hide(section); return; }

  const today = DAYS_SQ[new Date().getDay()];
  tbody.innerHTML = Object.entries(hours).map(([day, h]) => `
    <tr class="${day === today ? 'today' : ''}">
      <td>${day}${day === today ? ' <span style="font-size:11px;background:var(--primary);color:#fff;padding:2px 6px;border-radius:4px;margin-left:6px">Sot</span>' : ''}</td>
      <td>${h}</td>
    </tr>`).join('');
}

async function loadProviders() {
  const section = document.getElementById('team-section');
  const grid = document.getElementById('team-grid');
  if (!section || !grid) return;

  const t = window.__BIZAL_TENANT__;
  const showTeam = ['clinic','barbershop','spa','gym','tattoo','lawyer','language_school','tutoring'].includes(t?.business_type);
  if (!showTeam) return;

  const resp = await API.get('/appointments/providers/');
  if (!resp.ok) return;
  const data = await resp.json();
  const providers = data.results || data;
  if (!providers.length) return;

  const title = document.getElementById('team-title');
  const labels = { clinic: 'Mjekët Tanë', barbershop: 'Stilistët Tanë', spa: 'Terapistët', gym: 'Trajnerët', lawyer: 'Avokati Ynë', default: 'Ekipi Ynë' };
  if (title) title.textContent = labels[t.business_type] || labels.default;

  grid.innerHTML = providers.map(p => `
    <div class="team-card">
      ${p.avatar
        ? `<img class="team-avatar" src="${p.avatar}" alt="${p.name}" loading="lazy" />`
        : `<div class="team-avatar-placeholder">${p.name.charAt(0)}</div>`
      }
      <div class="team-name">${p.title ? p.title + ' ' : ''}${p.name}</div>
      ${p.specialties ? `<div class="team-title">${p.specialties}</div>` : ''}
      ${p.bio ? `<div class="team-bio">${p.bio}</div>` : ''}
    </div>`).join('');
  show(section);
}

function buildMap(t) {
  const section = document.getElementById('map-section');
  const embed = document.getElementById('map-embed');
  const addr = document.getElementById('map-address');
  if (!section || !embed || !t.address) return;

  const query = encodeURIComponent(`${t.address}, ${t.city || 'Albania'}`);
  if (addr) addr.textContent = `${t.address}${t.city ? ', ' + t.city : ''}`;
  embed.innerHTML = `<iframe
    src="https://maps.google.com/maps?q=${query}&output=embed&z=15"
    allowfullscreen loading="lazy" referrerpolicy="no-referrer-when-downgrade">
  </iframe>`;
  show(section);
}

function buildCTA(t) {
  const title = document.getElementById('cta-title');
  if (title) title.textContent = `Gati të Vizitoni ${t.name}?`;
}

window.addEventListener('tenantReady', async (e) => {
  const t = e.detail;
  buildStory(t);
  buildInfoCard(t);
  buildHours(t);
  buildCTA(t);
  buildMap(t);
  await loadProviders();
});

if (window.__BIZAL_TENANT__) window.dispatchEvent(new CustomEvent('tenantReady', { detail: window.__BIZAL_TENANT__ }));
