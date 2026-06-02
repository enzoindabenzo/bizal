/* contact.js — Contact Page */
const { API, show, hide, showFeedback, starHTML, formatDate, toast } = window.BizAL;
let reviewRating = 0;

function buildContactInfo(t) {
  const el = document.getElementById('contact-info-items');
  if (!el) return;
  const items = [];
  if (t.phone) items.push(['📞','Telefon',`<a href="tel:${t.phone}">${t.phone}</a>`]);
  if (t.email) items.push(['✉️','Email',`<a href="mailto:${t.email}">${t.email}</a>`]);
  if (t.address || t.city) items.push(['📍','Adresa',`${t.address || ''}${t.city ? ', '+t.city:''}`]);
  if (t.whatsapp) items.push(['💬','WhatsApp',`<a href="https://wa.me/${t.whatsapp.replace(/\D/g,'')}" target="_blank">+${t.whatsapp.replace(/\D/g,'')}</a>`]);

  el.innerHTML = items.map(([icon,label,value]) => `
    <div class="contact-info-item">
      <div class="contact-info-icon">${icon}</div>
      <div>
        <div class="contact-info-label">${label}</div>
        <div class="contact-info-value">${value}</div>
      </div>
    </div>`).join('');

  // Social
  const social = document.getElementById('contact-social');
  const socialLinks = document.getElementById('contact-social-links');
  if (social && socialLinks && t.plan === 'enterprise') {
    const links = [];
    if (t.facebook) links.push(`<a href="${t.facebook}" class="social-link" target="_blank" rel="noopener">📘 Facebook</a>`);
    if (t.instagram) links.push(`<a href="${t.instagram}" class="social-link" target="_blank" rel="noopener">📸 Instagram</a>`);
    if (t.tiktok) links.push(`<a href="${t.tiktok}" class="social-link" target="_blank" rel="noopener">🎵 TikTok</a>`);
    if (links.length) { socialLinks.innerHTML = links.join(''); show(social); }
  }

  // Hours
  const hours = document.getElementById('contact-hours');
  const hoursList = document.getElementById('contact-hours-list');
  if (hours && hoursList && t.business_hours && Object.keys(t.business_hours).length) {
    hoursList.innerHTML = Object.entries(t.business_hours).map(([d,h]) =>
      `<div class="contact-hours-row"><span>${d}</span><span>${h}</span></div>`
    ).join('');
    show(hours);
  }
}

async function loadReviews(t) {
  if (!t.has_reviews) return;
  const section = document.getElementById('reviews-on-contact');
  const grid = document.getElementById('contact-reviews-grid');
  if (!section || !grid) return;

  const resp = await API.get('/reviews/?limit=6');
  if (!resp.ok) return;
  const data = await resp.json();
  const reviews = data.results || data;
  if (!reviews.length) return;

  show(section);
  grid.innerHTML = reviews.map(r => `
    <div class="review-card">
      <div class="review-stars">${starHTML(r.rating)}</div>
      <p class="review-comment">${r.comment}</p>
      <div class="review-author">${r.user_name} <span class="review-date">· ${formatDate(r.created_at)}</span></div>
    </div>`).join('');

  if (API.isLoggedIn()) {
    show(document.getElementById('review-form-card'));
    initReviewForm();
  }
}

function initReviewForm() {
  const stars = document.querySelectorAll('#star-picker .star');
  stars.forEach(s => {
    s.addEventListener('click', () => {
      reviewRating = parseInt(s.dataset.value);
      stars.forEach(x => x.classList.toggle('active', parseInt(x.dataset.value) <= reviewRating));
    });
    s.addEventListener('mouseover', () => {
      stars.forEach(x => x.classList.toggle('active', parseInt(x.dataset.value) <= parseInt(s.dataset.value)));
    });
    s.addEventListener('mouseout', () => {
      stars.forEach(x => x.classList.toggle('active', parseInt(x.dataset.value) <= reviewRating));
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
      toast('Faleminderit për vlerësimin! ✓');
      loadReviews(window.__BIZAL_TENANT__);
    } else {
      toast('Gabim. Provoni përsëri.', 'error');
    }
  });
}

function initContactForm() {
  document.getElementById('send-contact')?.addEventListener('click', async () => {
    const name = document.getElementById('c-name')?.value.trim();
    const email = document.getElementById('c-email')?.value.trim();
    const phone = document.getElementById('c-phone')?.value.trim();
    const subject = document.getElementById('c-subject')?.value.trim();
    const message = document.getElementById('c-message')?.value.trim();
    const fb = document.getElementById('contact-feedback');

    if (!name || !email || !message) {
      showFeedback(fb, 'Emri, emaili dhe mesazhi janë të detyrueshme.', 'error');
      return;
    }

    const btn = document.getElementById('send-contact');
    btn.disabled = true; btn.textContent = 'Duke dërguar...';

    const resp = await API.post('/contact/', { name, email, phone, subject, message });
    btn.disabled = false;
    btn.innerHTML = `<svg viewBox="0 0 20 20" fill="currentColor" width="18" height="18" style="margin-right:8px"><path d="M10.894 2.553a1 1 0 00-1.788 0l-7 14a1 1 0 001.169 1.409l5-1.429A1 1 0 009 15.571V11a1 1 0 112 0v4.571a1 1 0 00.725.962l5 1.428a1 1 0 001.17-1.408l-7-14z"/></svg>Dërgo Mesazhin`;

    if (resp.ok) {
      showFeedback(fb, '✓ Mesazhi u dërgua me sukses! Do ju kthehemi së shpejti.', 'success');
      ['c-name','c-email','c-phone','c-subject','c-message'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = '';
      });
    } else {
      showFeedback(fb, 'Gabim në dërgimin e mesazhit. Provoni përsëri.', 'error');
    }
  });
}

window.addEventListener('tenantReady', async (e) => {
  const t = e.detail;
  buildContactInfo(t);
  initContactForm();
  await loadReviews(t);
});

if (window.__BIZAL_TENANT__) window.dispatchEvent(new CustomEvent('tenantReady', { detail: window.__BIZAL_TENANT__ }));
