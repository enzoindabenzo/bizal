/* ═══════════════════════════════════════════════════════
   BizAL — ui.js
   Shared UI utilities used by all pages.
   No dependencies. Load before page-specific scripts.
═══════════════════════════════════════════════════════ */

/* ── Theme ────────────────────────────────────────────── */
const Theme = (() => {
  const KEY = 'bizal-theme';
  let current = localStorage.getItem(KEY) || 'light';

  function apply(t) {
    current = t;
    document.documentElement.setAttribute('data-theme', t);
    localStorage.setItem(KEY, t);
    document.querySelectorAll('[data-theme-toggle]').forEach(btn => {
      btn.textContent = t === 'dark' ? '☀' : '☾';
      btn.title = t === 'dark' ? 'Light mode' : 'Dark mode';
    });
  }

  function toggle() { apply(current === 'dark' ? 'light' : 'dark'); }
  function init()   { apply(current); }
  return { init, toggle, current: () => current };
})();

/* ── Toast ────────────────────────────────────────────── */
function toast(msg, type = 'default', duration = 3200) {
  let wrap = document.getElementById('toast-wrap');
  if (!wrap) {
    wrap = document.createElement('div');
    wrap.id = 'toast-wrap';
    wrap.className = 'toast-wrap';
    document.body.appendChild(wrap);
  }
  const el = document.createElement('div');
  el.className = 'toast' + (type !== 'default' ? ` toast-${type}` : '');
  el.textContent = msg;
  wrap.appendChild(el);
  setTimeout(() => {
    el.style.opacity = '0';
    el.style.transform = 'translateX(10px)';
    el.style.transition = '.2s ease';
    setTimeout(() => el.remove(), 220);
  }, duration);
}

/* ── Modal ────────────────────────────────────────────── */
const Modal = (() => {
  function open(id)  {
    const m = document.getElementById(id);
    if (!m) return;
    m.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
    m.querySelector('.modal-backdrop')?.addEventListener('click', () => close(id), { once: true });
    m.querySelector('.modal-close')?.addEventListener('click', () => close(id), { once: true });
  }
  function close(id) {
    const m = document.getElementById(id);
    if (!m) return;
    m.classList.add('hidden');
    document.body.style.overflow = '';
  }
  function closeAll() {
    document.querySelectorAll('.modal:not(.hidden)').forEach(m => {
      m.classList.add('hidden');
    });
    document.body.style.overflow = '';
  }
  return { open, close, closeAll };
})();

/* ── Confirm dialog ───────────────────────────────────── */
function showConfirm(msg, title = 'Konfirmo') {
  return new Promise(resolve => {
    let m = document.getElementById('confirm-modal');
    if (!m) {
      m = document.createElement('div');
      m.id = 'confirm-modal';
      m.className = 'modal hidden';
      m.innerHTML = `
        <div class="modal-backdrop"></div>
        <div class="modal-box" style="max-width:380px">
          <button class="modal-close">✕</button>
          <div class="modal-title" id="confirm-title"></div>
          <p id="confirm-msg" style="color:var(--text-muted);font-size:13.5px;margin-bottom:22px;line-height:1.5"></p>
          <div class="flex gap-2" style="justify-content:flex-end">
            <button class="btn btn-ghost btn-sm" id="confirm-no">Anulo</button>
            <button class="btn btn-primary btn-sm" id="confirm-yes">Konfirmo</button>
          </div>
        </div>`;
      document.body.appendChild(m);
    }
    document.getElementById('confirm-title').textContent = title;
    document.getElementById('confirm-msg').textContent   = msg;
    Modal.open('confirm-modal');
    const yes = document.getElementById('confirm-yes');
    const no  = document.getElementById('confirm-no');
    const cleanup = (val) => {
      Modal.close('confirm-modal');
      yes.replaceWith(yes.cloneNode(true));
      no.replaceWith(no.cloneNode(true));
      resolve(val);
    };
    document.getElementById('confirm-yes').addEventListener('click', () => cleanup(true),  { once: true });
    document.getElementById('confirm-no') .addEventListener('click', () => cleanup(false), { once: true });
  });
}

/* ── Escape HTML ──────────────────────────────────────── */
function esc(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g,'&amp;')
    .replace(/</g,'&lt;')
    .replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;')
    .replace(/'/g,'&#39;');
}
// Alias so templates that use escHtml() also resolve to this single definition.
window.esc = esc;
window.escHtml = esc;

/* ── Parse JWT (client-side decode, no verify) ───────── */
function parseJWT(token) {
  try { return JSON.parse(atob(token.split('.')[1].replace(/-/g,'+').replace(/_/g,'/'))); }
  catch { return null; }
}

/* ── Format date ──────────────────────────────────────── */
function fmtDate(str, opts) {
  if (!str) return '—';
  const d = new Date(str);
  if (isNaN(d)) return str;
  return d.toLocaleDateString('sq-AL', opts || { day:'numeric', month:'short', year:'numeric' });
}
function fmtDateTime(str) {
  return fmtDate(str, { day:'numeric', month:'short', year:'numeric', hour:'2-digit', minute:'2-digit' });
}

/* ── Format currency ──────────────────────────────────── */
function fmtALL(val) {
  const n = parseFloat(val);
  if (isNaN(n)) return '—';
  return new Intl.NumberFormat('sq-AL').format(n) + ' L';
}
function fmtEUR(val) {
  const n = parseFloat(val);
  if (isNaN(n)) return '—';
  return '€' + n.toFixed(2);
}

/* ── Feedback helper ──────────────────────────────────── */
function showFeedback(id, msg, type = 'error') {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = msg;
  el.className = `feedback feedback-${type}`;
  el.classList.remove('hidden');
}
function hideFeedback(id) {
  const el = document.getElementById(id);
  if (el) el.classList.add('hidden');
}

/* ── Debounce ─────────────────────────────────────────── */
function debounce(fn, ms = 280) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

/* ── Init on DOM ready ────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  Theme.init();
  document.addEventListener('click', e => {
    if (e.target.matches('[data-theme-toggle]')) Theme.toggle();
  });
  // Close modal on Escape
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') Modal.closeAll();
  });
});
