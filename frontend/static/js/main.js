/* main.js — Landing page scripts */

// Slug availability
const slugInput  = document.getElementById('signup-slug');
const slugStatus = document.getElementById('slug-status');

function debounce(fn, d) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), d); }; }

if (slugInput) {
  slugInput.addEventListener('input', debounce(async () => {
    let slug = slugInput.value.trim().toLowerCase().replace(/[^a-z0-9-]/g, '-').replace(/-+/g, '-');
    slugInput.value = slug;
    if (!slug || slug.length < 3) {
      slugStatus.textContent = slug.length ? 'Min 3 karaktere' : '';
      slugStatus.className = 'slug-status taken';
      return;
    }
    slugStatus.textContent = '...';
    slugStatus.className = 'slug-status';
    const resp = await fetch(`/api/tenant/check-slug/?slug=${encodeURIComponent(slug)}`);
    const data = await resp.json();
    slugStatus.textContent = data.available ? '✓ E lirë' : '✗ E zënë';
    slugStatus.className   = `slug-status ${data.available ? 'ok' : 'taken'}`;
  }, 500));
}

// Signup
document.getElementById('signup-btn')?.addEventListener('click', async () => {
  const business_name   = document.getElementById('signup-name')?.value.trim();
  const slug            = document.getElementById('signup-slug')?.value.trim();
  const business_type   = document.getElementById('signup-type')?.value;
  const owner_name      = document.getElementById('signup-owner-name')?.value.trim();
  const owner_email     = document.getElementById('signup-email')?.value.trim();
  const owner_password  = document.getElementById('signup-password')?.value;
  const msg             = document.getElementById('signup-msg');
  const btn             = document.getElementById('signup-btn');

  if (!business_name || !slug || !business_type || !owner_name || !owner_email || !owner_password) {
    showFeedback(msg, 'Ju lutemi plotësoni të gjitha fushat.', 'error');
    return;
  }
  if (owner_password.length < 8) {
    showFeedback(msg, 'Fjalëkalimi duhet të ketë të paktën 8 karaktere.', 'error');
    return;
  }

  btn.disabled = true; btn.textContent = 'Duke u krijuar...';

  const resp = await fetch('/api/tenant/signup/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ business_name, slug, business_type, owner_name, owner_email, owner_password }),
  });
  const data = await resp.json();
  btn.disabled = false; btn.textContent = 'Krijo Llogarinë →';

  if (resp.ok) {
    msg.className = 'feedback success';
    msg.innerHTML = `🎉 <strong>${business_name}</strong> u regjistrua!<br>
      Subdomain: <strong>${slug}.bizal.al</strong><br>
      Ekipi ynë do ju aktivizojë brenda 24 orësh.`;
    msg.classList.remove('hidden');
  } else {
    showFeedback(msg, Object.values(data).flat().join(' ') || 'Gabim. Provoni përsëri.', 'error');
  }
});

// Smooth scroll for anchor links
document.querySelectorAll('a[href^="#"]').forEach(a => {
  a.addEventListener('click', e => {
    const target = document.querySelector(a.getAttribute('href'));
    if (target) { e.preventDefault(); target.scrollIntoView({ behavior: 'smooth' }); }
  });
});

// Sticky nav shadow
window.addEventListener('scroll', () => {
  const nav = document.querySelector('.navbar');
  if (nav) nav.style.boxShadow = window.scrollY > 20 ? '0 2px 20px rgba(0,0,0,.12)' : '';
});

function showFeedback(el, msg, type) {
  if (!el) return;
  el.textContent = msg;
  el.className = `feedback ${type}`;
  el.classList.remove('hidden');
}
