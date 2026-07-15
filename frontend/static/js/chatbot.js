/**
 * BizBot  v3
 * ──────────
 * BizBot.init()               → marketing chatbot  (index/main domain)
 * BizBot.init({ slug, name, type, phone, whatsapp })
 *                             → enterprise tenant chatbot  (main.html SPA)
 *
 * New in v3:
 *   • 6-key rotation (3 Groq + 3 OpenRouter) — switches transparently at 80 % usage
 *   • Seriousness filter: after 5 trivial exchanges bot stops (unrelated questions)
 *   • Staff live-reply: staff can inject a real reply from tenant admin; frontend polls
 *   • Handoff: visitor hands off → bot pauses → staff types → message appears in chat
 *   • session_id sent on every request so backend can track per-conversation state
 */

(function () {
  'use strict';

  const CHAT_URL         = '/api/chatbot/chat/';
  const HANDOFF_URL      = '/api/chatbot/handoff/';
  const POLL_URL         = '/api/chatbot/poll/';   // + session_id

  const POLL_INTERVAL_MS = 4000;   // check for staff replies every 4 s

  // ── Session ID — cryptographically secure, browser-native ────────────────
  // C-1 FIX: Declared as `let` so the server-issued HMAC-signed token can
  // replace the initial random hex string on the first chat() response.
  // The plain hex string is never a valid signed token (it has no '.'
  // separator) and _verify_session_token() rejects it immediately —
  // meaning the server always minted a fresh UUID per message, making the
  // trivial-message counter, per-session daily cap, handoff state, and poll
  // queue permanently broken. Updating SESSION_ID from the first chat()
  // response activates all session-scoped features.
  let SESSION_ID = Array.from(crypto.getRandomValues(new Uint8Array(16)))
    .map(function (b) { return b.toString(16).padStart(2, '0'); }).join('');

  // ── State ─────────────────────────────────────────────────────────────────
  let _slug           = '';
  let _bizName        = 'BizBot';
  let _isOpen         = false;
  let _loading        = false;
  let _stopped        = false;   // seriousness filter hit
  let _authGated       = false;  // true when visitor isn't logged in — chat locked
  let _handoffActive  = false;   // true when real staff has taken over
  let _pollTimer      = null;
  let _handoffPending = false;
  let _history        = [];      // [{role, content}]

  // DOM refs
  let $win, $msgs, $input, $send, $handoffBar, $subTitle;

  // ── CSS ───────────────────────────────────────────────────────────────────
  // v4: self-contained light + dark palette (--bb-* custom properties) so the
  // widget always matches the host page's data-theme attribute (set by
  // Theme in ui.js on both main.html and the tenant storefront) instead of
  // silently falling back to a generic navy/indigo theme that never adapted
  // to dark mode and clashed with the site's warm cream/ink/red brand.
  const CSS = `
  :root{
    --bb-bg:#FFFFFF; --bb-panel:#FBF8F2; --bb-surface:#FFFFFF; --bb-surface2:#F2EDE3;
    --bb-border:#E4DDD0; --bb-text:#1A1610; --bb-muted:#6A6056;
    --bb-ink:#1A1610; --bb-ink2:#2A2118; --bb-red:#C0251B; --bb-red2:#A01D15;
    --bb-on-ink:#F7F4EE; --bb-shadow:0 10px 48px rgba(26,22,16,.16), 0 2px 10px rgba(26,22,16,.08);
    --bb-shadow-fab:0 4px 18px rgba(26,22,16,.28);
  }
  [data-theme="dark"]{
    --bb-bg:#241E15; --bb-panel:#1E1811; --bb-surface:#2F2819; --bb-surface2:#3B331F;
    --bb-border:#4A4230; --bb-text:#F2EBDF; --bb-muted:#A79C8C;
    --bb-ink:#16120B; --bb-ink2:#0F0C07; --bb-red:#D8362B; --bb-red2:#C0251B;
    --bb-on-ink:#F2EBDF; --bb-shadow:0 10px 48px rgba(0,0,0,.5), 0 2px 10px rgba(0,0,0,.3);
    --bb-shadow-fab:0 4px 18px rgba(0,0,0,.45);
  }

  #bb-fab{position:fixed;bottom:24px;right:24px;width:56px;height:56px;border-radius:50%;
    background:var(--bb-ink);color:var(--bb-on-ink);border:none;cursor:pointer;display:flex;
    align-items:center;justify-content:center;box-shadow:var(--bb-shadow-fab);
    z-index:9998;transition:transform .2s cubic-bezier(.4,0,.2,1),background .2s;font-size:0}
  #bb-fab:hover{transform:scale(1.08) translateY(-1px);background:var(--bb-red)}
  #bb-fab:active{transform:scale(.97)}
  #bb-fab svg{width:25px;height:25px}
  #bb-fab .bb-badge{position:absolute;top:1px;right:1px;width:13px;height:13px;
    background:var(--bb-red);border-radius:50%;border:2px solid var(--bb-ink);display:none}
  #bb-fab .bb-badge.show{display:block;animation:bb-badge-pop .3s cubic-bezier(.34,1.56,.64,1)}

  @keyframes bb-badge-pop{from{transform:scale(0)}to{transform:scale(1)}}

  #bb-win{position:fixed;bottom:90px;right:24px;width:378px;max-width:calc(100vw - 28px);
    height:520px;max-height:calc(100vh - 118px);background:var(--bb-panel);
    border:1px solid var(--bb-border);border-radius:20px;box-shadow:var(--bb-shadow);
    display:flex;flex-direction:column;overflow:hidden;z-index:9999;font-family:inherit;
    transition:opacity .22s cubic-bezier(.4,0,.2,1),transform .22s cubic-bezier(.4,0,.2,1);
    transform-origin:bottom right}
  #bb-win.bb-hide{opacity:0;pointer-events:none;transform:translateY(14px) scale(.96)}

  #bb-head{background:linear-gradient(135deg,var(--bb-ink2) 0%,var(--bb-ink) 100%);
    color:var(--bb-on-ink);padding:15px 16px 13px;
    display:flex;align-items:center;gap:11px;flex-shrink:0;position:relative}
  #bb-head::after{content:'';position:absolute;left:0;right:0;bottom:0;height:2px;
    background:linear-gradient(90deg,var(--bb-red) 0%,transparent 70%)}
  #bb-head .bb-av{width:36px;height:36px;border-radius:50%;
    background:var(--bb-red);display:flex;align-items:center;justify-content:center;
    font-size:17px;flex-shrink:0;box-shadow:0 0 0 2px rgba(255,255,255,.08)}
  #bb-head .bb-t{font-weight:700;font-size:.95rem;line-height:1.2;letter-spacing:-.01em}
  #bb-head .bb-s{font-size:.71rem;opacity:.7;margin-top:2px}
  #bb-x{margin-left:auto;background:none;border:none;color:var(--bb-on-ink);cursor:pointer;
    opacity:.65;padding:6px;border-radius:6px;display:flex;line-height:1;transition:opacity .15s,background .15s}
  #bb-x:hover{opacity:1;background:rgba(255,255,255,.08)}

  #bb-msgs{flex:1;overflow-y:auto;padding:16px 13px;display:flex;flex-direction:column;
    gap:10px;background:var(--bb-panel);scroll-behavior:smooth}
  #bb-msgs::-webkit-scrollbar{width:6px}
  #bb-msgs::-webkit-scrollbar-thumb{background:var(--bb-border);border-radius:3px}
  #bb-msgs::-webkit-scrollbar-track{background:transparent}

  .bb-m{max-width:85%;padding:9px 13px;border-radius:16px;font-size:.875rem;
    line-height:1.55;word-break:break-word;white-space:pre-wrap;animation:bb-msg-in .18s cubic-bezier(.4,0,.2,1)}
  @keyframes bb-msg-in{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:translateY(0)}}
  .bb-m.bot{background:var(--bb-surface);border:1px solid var(--bb-border);border-bottom-left-radius:4px;
    align-self:flex-start;color:var(--bb-text)}
  .bb-m.staff{background:rgba(26,107,66,.1);border:1px solid rgba(26,107,66,.3);
    border-bottom-left-radius:4px;align-self:flex-start;color:var(--bb-text)}
  .bb-m.usr{background:var(--bb-ink);color:var(--bb-on-ink);border-bottom-right-radius:4px;
    align-self:flex-end}
  .bb-m.typing{opacity:.7;font-style:italic;animation:bb-msg-in .18s cubic-bezier(.4,0,.2,1),bb-pulse 1.1s ease-in-out infinite}
  @keyframes bb-pulse{0%,100%{opacity:.45}50%{opacity:.85}}
  .bb-m.err{background:rgba(192,37,27,.08);color:var(--bb-red);border:1px solid rgba(192,37,27,.3)}
  .bb-m.sys{align-self:center;background:rgba(184,134,11,.1);color:var(--bb-text);
    border:1px solid rgba(184,134,11,.35);font-size:.78rem;border-radius:10px;text-align:center;max-width:92%}

  /* Staff name label above staff message */
  .bb-staff-label{font-size:.7rem;color:#1A6B42;font-weight:700;margin-bottom:2px;
    align-self:flex-start;padding-left:4px}

  /* Quick-reply chips */
  .bb-chips{display:flex;flex-wrap:wrap;gap:6px;padding:4px 0 2px;align-self:flex-start}
  .bb-chip{background:var(--bb-surface);border:1px solid var(--bb-border);border-radius:20px;padding:6px 13px;
    font-size:.78rem;font-weight:500;cursor:pointer;white-space:nowrap;color:var(--bb-text);
    transition:background .15s,border-color .15s,color .15s,transform .15s}
  .bb-chip:hover{background:var(--bb-red);color:#fff;border-color:transparent;transform:translateY(-1px)}

  /* Handoff bar */
  #bb-handoff{display:none;gap:8px;padding:9px 12px;border-top:1px solid var(--bb-border);
    background:rgba(26,107,66,.08);flex-shrink:0;align-items:center;flex-wrap:wrap}
  #bb-handoff.show{display:flex}
  #bb-handoff p{font-size:.8rem;color:var(--bb-text);flex:1;margin:0;min-width:120px;font-weight:500}
  .bb-hbtn{border:none;border-radius:20px;padding:6px 14px;font-size:.8rem;font-weight:700;
    cursor:pointer;white-space:nowrap;transition:filter .15s,transform .15s}
  .bb-hbtn:hover{filter:brightness(1.08);transform:translateY(-1px)}
  .bb-hbtn.wa{background:#25d366;color:#fff}
  .bb-hbtn.ph{background:var(--bb-ink);color:var(--bb-on-ink)}

  #bb-foot{display:flex;align-items:center;gap:8px;padding:11px 12px;
    border-top:1px solid var(--bb-border);background:var(--bb-bg);flex-shrink:0}
  #bb-inp{flex:1;border:1px solid var(--bb-border);border-radius:22px;padding:9px 15px;
    font-size:.875rem;outline:none;resize:none;font-family:inherit;line-height:1.45;
    max-height:88px;overflow-y:auto;background:var(--bb-surface);color:var(--bb-text);
    transition:border-color .15s,box-shadow .15s}
  #bb-inp::placeholder{color:var(--bb-muted)}
  #bb-inp:focus{border-color:var(--bb-red);box-shadow:0 0 0 3px rgba(192,37,27,.12)}
  #bb-inp:disabled{background:var(--bb-surface2);color:var(--bb-muted)}
  #bb-snd{width:38px;height:38px;flex-shrink:0;border-radius:50%;
    background:var(--bb-ink);border:none;cursor:pointer;color:var(--bb-on-ink);
    display:flex;align-items:center;justify-content:center;transition:background .18s,transform .15s}
  #bb-snd:hover:not(:disabled){background:var(--bb-red);transform:translateY(-1px)}
  #bb-snd:disabled{opacity:.38;cursor:not-allowed}
  .bb-spin{width:18px;height:18px;animation:bb-rotate .7s linear infinite}
  @keyframes bb-rotate{to{transform:rotate(360deg)}}

  .bb-brand{text-align:center;font-size:.67rem;color:var(--bb-muted);padding:4px 0 6px;
    flex-shrink:0;background:var(--bb-bg)}

  @media(max-width:420px){
    #bb-win{right:8px;width:calc(100vw - 16px)}
    #bb-fab{bottom:16px;right:16px}
  }
  `;

  const I_CHAT  = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>`;
  const I_CLOSE = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`;
  const I_SEND  = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>`;
  const I_SPINNER = `<svg viewBox="0 0 24 24" fill="none" class="bb-spin"><circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="2.2" opacity=".25"/><path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>`;
  const I_WA    = `<svg viewBox="0 0 24 24" fill="currentColor" width="14" height="14"><path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 0 1-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 0 1-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 0 1 2.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0 0 12.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 0 0 5.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 0 0-3.48-8.413z"/></svg>`;

  // ── Init ──────────────────────────────────────────────────────────────────
  function init(opts) {
    opts = opts || {};
    _slug    = opts.slug    || '';
    _bizName = opts.name    || (_slug ? 'Asistenti' : 'BizBot');

    injectCSS();
    buildFAB();
    buildWindow(opts);
    showWelcome(opts);
  }

  function injectCSS() {
    if (document.getElementById('bb-css')) return;
    var s = document.createElement('style');
    s.id = 'bb-css';
    s.textContent = CSS;
    document.head.appendChild(s);
  }

  function buildFAB() {
    var btn = document.createElement('button');
    btn.id = 'bb-fab';
    btn.setAttribute('aria-label', 'Hap asistentin AI');
    btn.innerHTML = I_CHAT + '<span class="bb-badge" id="bb-badge"></span>';
    btn.addEventListener('click', toggleWindow);
    document.body.appendChild(btn);
  }

  function buildWindow(opts) {
    $win = document.createElement('div');
    $win.id = 'bb-win';
    $win.classList.add('bb-hide');
    $win.setAttribute('role', 'dialog');
    $win.setAttribute('aria-modal', 'true');
    $win.setAttribute('aria-label', _bizName + ' chatbot');

    var statusDot = opts.slug
      ? '<span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:#4ade80;margin-right:4px"></span>Online'
      : '<span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:#4ade80;margin-right:4px"></span>AI • Online';

    $win.innerHTML = `
      <div id="bb-head">
        <div class="bb-av">🤖</div>
        <div>
          <div class="bb-t">${esc(_bizName)}</div>
          <div class="bb-s" id="bb-sub">${statusDot}</div>
        </div>
        <button id="bb-x" aria-label="Mbyll">${I_CLOSE}</button>
      </div>
      <div id="bb-msgs" role="log" aria-live="polite" aria-label="Biseda"></div>
      <div id="bb-handoff" role="region" aria-label="Kontaktoni stafin">
        <p>Dëshironi të flisni me stafin? 👋</p>
      </div>
      <div id="bb-foot">
        <textarea id="bb-inp" rows="1" placeholder="Shkruaj këtu…" aria-label="Mesazhi juaj"></textarea>
        <button id="bb-snd" aria-label="Dërgo">${I_SEND}</button>
      </div>
      <div class="bb-brand">Powered by BizAL AI</div>
    `;
    document.body.appendChild($win);

    $msgs       = document.getElementById('bb-msgs');
    $input      = document.getElementById('bb-inp');
    $send       = document.getElementById('bb-snd');
    $handoffBar = document.getElementById('bb-handoff');
    $subTitle   = document.getElementById('bb-sub');

    document.getElementById('bb-x').addEventListener('click', closeWindow);
    $send.addEventListener('click', sendMessage);
    $input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
    });
    $input.addEventListener('input', function () {
      this.style.height = 'auto';
      this.style.height = Math.min(this.scrollHeight, 88) + 'px';
    });
  }

  function showWelcome(opts) {
    if (!isAuthed()) {
      if (opts.slug) {
        addBotHTML(
          'Tungjatjeta! 👋 Jam asistenti AI i <strong>' + esc(opts.name || 'biznesit') + '</strong>.'
        );
      } else {
        addBot('Tungjatjeta! 👋 Jam BizBot, asistenti AI i BizAL.');
      }
      showAuthGate();
      return;
    }
    if (opts.slug) {
      addBotHTML(
        'Tungjatjeta! 👋 Jam asistenti AI i <strong>' + esc(opts.name || 'biznesit') + '</strong>. ' +
        'Mund t\'ju ndihmoj me informacione mbi shërbimet, oraret, çmimet, ose t\'ju lidh me stafin.'
      );
      addChips([
        { label: '🕐 Oraret',   msg: 'Cilat janë oraret e hapjes?' },
        { label: '💰 Çmimet',   msg: 'Çfarë çmimesh keni?' },
        { label: '📋 Shërbime', msg: 'Çfarë shërbimesh ofroni?' },
        { label: '👤 Stafi',    msg: 'A mund të flas me dikë nga stafi?' },
      ]);
    } else {
      addBot(
        'Tungjatjeta! 👋 Jam BizBot, asistenti AI i BizAL. ' +
        'Si mund t\'ju ndihmoj sot?'
      );
      addChips([
        { label: '💼 Planet',    msg: 'Cilat janë planet dhe çmimet?' },
        { label: '⚙️ Funksionet', msg: 'Çfarë funksionesh ofron BizAL?' },
        { label: '🚀 Si filloj',  msg: 'Si mund të filloj me BizAL?' },
        { label: '🔄 Demo',       msg: 'A mund të shoh një demo?' },
      ]);
    }
  }

  // ── Auth gating ──────────────────────────────────────────────────────────
  // The chatbot now requires a logged-in visitor. We deliberately do NOT
  // route these requests through Auth.apiFetch(): its 401 handling does
  // `window.location.href = '/'` when a refresh fails, which would yank an
  // anonymous visitor off a tenant's storefront page just for tapping the
  // chat bubble. Instead we attach a fresh token ourselves when one is
  // available and fall back to a locked "please log in" state — no
  // navigation — when it isn't.
  function isAuthed() {
    return typeof Auth !== 'undefined' && Auth.isLoggedIn();
  }

  // Ensures an in-memory access token is present if a refresh token exists
  // (covers the common case where the page just loaded and the in-memory
  // token hasn't been restored yet). Never throws.
  function ensureFreshToken() {
    if (typeof Auth === 'undefined') return Promise.resolve();
    if (Auth.getAccess() || !Auth.getRefresh()) return Promise.resolve();
    return Auth.refreshAccess().catch(function () { /* will 401 below; handled by caller */ });
  }

  function authHeaders() {
    return (typeof Auth !== 'undefined' && Auth.headers) ? Auth.headers() : {};
  }

  function lockForAuth() {
    _authGated = true;
    $input.disabled = true;
    $input.placeholder = 'Identifikohuni për të përdorur asistentin.';
    $send.disabled = true;
    setStatus('🔒 Kërkohet identifikimi');
  }

  function showAuthGate() {
    lockForAuth();
    addBot(
      'Duhet të identifikoheni për të përdorur këtë asistent. Klikoni butonin "Hyr" ' +
      'sipër faqes për t\'u identifikuar, më pas rifreskoni faqen për të vazhduar bisedën.',
      'sys'
    );
  }


  function toggleWindow() { _isOpen ? closeWindow() : openWindow(); }

  function openWindow() {
    _isOpen = true;
    $win.classList.remove('bb-hide');
    document.getElementById('bb-badge').classList.remove('show');
    $input.focus();
    scrollBottom();
    // Resume polling if a handoff was active when the window was closed
    if (_handoffActive) startPolling();
  }

  function closeWindow() {
    _isOpen = false;
    $win.classList.add('bb-hide');
    // Pause polling while window is closed — will resume in openWindow()
    stopPolling();
  }

  // ── Messaging ──────────────────────────────────────────────────────────────
  function sendMessage(text) {
    var msg = (typeof text === 'string') ? text : $input.value.trim();
    if (!msg || _loading || _stopped || _authGated) return;

    if (!isAuthed()) { showAuthGate(); return; }

    // If handoff is active, visitor is re-engaging — clear handoff state
    if (_handoffActive) {
      _handoffActive = false;
      stopPolling();
      setStatus(_slug ? '🟢 Online' : 'AI • Online');
    }

    addUser(msg);
    _history.push({ role: 'user', content: msg });
    $input.value = '';
    $input.style.height = 'auto';

    var typingEl = addBot('…', 'typing');
    _loading = true;
    setSendLoading(true);
    $input.disabled = true;
    setStatus('Duke shkruar…');

    var payload = {
      messages:   _history.slice(),
      session_id: SESSION_ID,
    };
    if (_slug) payload.tenant_slug = _slug;

    // Ground the reply in exactly what's rendered on screen right now
    // (pricing cards on the marketing site, or live services/menu/blog/
    // reviews content on a tenant storefront) — see collectPageContext().
    var pageContext = collectPageContext();
    if (pageContext) payload.page_context = pageContext;

    // doRequest attaches a fresh Bearer token and, on a 401 (expired/missing
    // token), attempts exactly one silent refresh + retry before giving up —
    // deliberately NOT using Auth.apiFetch here, since that helper navigates
    // to '/' on a failed refresh, which would knock an anonymous visitor off
    // a tenant's storefront page. A final 401 is surfaced as {status: 401}
    // and handled below by locking the widget, not navigating away.
    function doRequest(retried) {
      return ensureFreshToken().then(function () {
        return fetch(CHAT_URL, {
          method:  'POST',
          headers: Object.assign({ 'Content-Type': 'application/json' }, authHeaders()),
          body:    JSON.stringify(payload),
        });
      }).then(function (r) {
        if (r.status === 401 && !retried && typeof Auth !== 'undefined' && Auth.getRefresh()) {
          return Auth.refreshAccess()
            .then(function () { return doRequest(true); })
            .catch(function () { return { ok: false, d: {}, status: 401 }; });
        }
        return r.json().then(function (d) { return { ok: r.ok, d: d, status: r.status }; });
      });
    }

    doRequest(false)
    .then(function (res) {
      typingEl.remove();

      if (res.status === 401) {
        showAuthGate();
        return;
      }

      if (res.ok && res.d.reply && !res.d.capped) {
        var reply = res.d.reply;

        // C-1 FIX: Adopt the HMAC-signed session token returned by the server.
        // On the very first message (or any message where the server rejects
        // the current SESSION_ID as invalid/forged), the server mints a new
        // signed token and returns it as session_id. Storing it here ensures
        // all subsequent chat, handoff, and poll requests carry a valid token
        // so the trivial-message counter, daily cap, and handoff state
        // accumulate correctly across messages.
        if (res.d.session_id) {
          SESSION_ID = res.d.session_id;
        }

        addBot(reply);
        _history.push({ role: 'assistant', content: reply });
        if (_history.length > 24) _history = _history.slice(-24);

        // Seriousness filter hit — bot stops answering unrelated messages
        if (res.d.stopped) {
          _stopped = true;
          $input.disabled = true;
          $input.placeholder = 'Biseda mbyllur — rifresko faqen për të filluar.';
          $send.disabled = true;
          setStatus('⛔ Limit i arritur');
          return;
        }

        // Key near limit — switch happened silently server-side; no UI noise needed
        // (near_limit flag available if you want to log or debug)

        // AI suggested handoff (enterprise only)
        if (res.d.handoff_hint && _slug) {
          showHandoffBar();
        }

      } else if (res.d && res.d.session_capped) {
        // Hard per-session message cap hit — show the message and lock
        // input, same treatment as the trivial-message "stopped" path,
        // since a capped session needs a page refresh either way.
        if (res.d.session_id) SESSION_ID = res.d.session_id;
        addBot(res.d.reply || 'Keni arritur limitin e mesazheve për këtë bisedë.', 'sys');
        _stopped = true;
        $input.disabled = true;
        $input.placeholder = 'Biseda mbyllur — rifresko faqen për të filluar.';
        $send.disabled = true;
        setStatus('⛔ Limit i arritur');
      } else if (res.d && res.d.capped) {
        // LOW-3 FIX: Server now returns 429 for daily cap; handle capped on any
        // status so the message renders in sys style (matches keys-exhausted path).
        addBot(res.d.reply || 'Limiti ditor i mesazheve u arrit.', 'sys');
      } else {
        addBot(res.d && res.d.error ? res.d.error : 'Ndodhi një gabim. Provoni përsëri.', 'err');
      }
    })
    .catch(function () {
      typingEl.remove();
      addBot('Nuk mund të lidhem me serverin. Kontrolloni internetin.', 'err');
    })
    .finally(function () {
      _loading = false;
      setSendLoading(false);
      if (!_stopped && !_authGated) {
        $input.disabled = false;
        setStatus(_slug ? '🟢 Online' : 'AI • Online');
        $input.focus();
      } else {
        $send.disabled = true;
      }
    });
  }

  // Swaps the send icon for a small spinner while a request is in flight,
  // instead of just disabling the button with no feedback.
  function setSendLoading(isLoading) {
    if (!$send) return;
    $send.disabled = isLoading;
    $send.innerHTML = isLoading ? I_SPINNER : I_SEND;
  }

  // ── Live page context ────────────────────────────────────────────────────
  // Scrapes a short, plain-text snapshot of what's actually rendered on the
  // visitor's screen right now and sends it up with every message, so the
  // backend can ground replies in real, current content instead of relying
  // only on the static system prompt (marketing site) or a periodically
  // cached DB snapshot (tenant storefront) that can miss free-text content
  // like blog posts or review comments. Truncated hard at 4000 chars to
  // match the backend cap; wrapped in try/catch so a page-structure change
  // never breaks sending a message.
  function collectPageContext() {
    try {
      return _slug ? collectTenantPageContext() : collectMarketingPageContext();
    } catch (e) {
      return '';
    }
  }

  // Marketing site (main.html): pull the live pricing plan cards so the bot
  // can quote exact current prices/features instead of saying "check the
  // website" — it IS the website.
  //
  // Also pulls the "Veçoritë" (Features) grid on #pg-vecorite. That section
  // sits in the DOM at all times (only .pg.on toggles visibility via CSS —
  // see main.css), so it's available regardless of which page the visitor
  // is currently viewing, same as the plan cards below. This gives the bot
  // real, developer-authored feature names/descriptions to ground
  // "what can BizAL do" style questions, instead of having nothing and
  // improvising a plausible-sounding but fabricated workflow.
  function collectMarketingPageContext() {
    var out = [];

    var cards = document.querySelectorAll('.plans .pc');
    cards.forEach(function (card) {
      var name  = textOf(card, '.pname');
      var price = textOf(card, '.pprice');
      var bill  = textOf(card, '.pbill');
      if (!name) return;
      var feats = Array.prototype.map.call(card.querySelectorAll('.plist li'), function (li) {
        var included = li.classList.contains('n') ? '✗' : '✓';
        return included + ' ' + li.textContent.trim();
      }).join('; ');
      out.push(
        name + ' — ' + price + (bill ? ' (' + bill + ')' : '') +
        (feats ? '\nFeatures: ' + feats : '')
      );
    });

    var featCards = document.querySelectorAll('#pg-vecorite .feats .fc');
    if (featCards.length) {
      var featLines = Array.prototype.map.call(featCards, function (fc) {
        var title = textOf(fc, '.ft');
        var desc  = textOf(fc, '.fp');
        return title ? (title + (desc ? ' — ' + desc : '')) : '';
      }).filter(Boolean);
      if (featLines.length) {
        out.push('[VEÇORITË / PRODUCT FEATURES]\n' + featLines.join('\n'));
      }
    }

    return out.join('\n\n').slice(0, 4000);
  }

  // Tenant storefront (index.html): pull visible text from the live-rendered
  // panels (services, menu, rentals, reviews, blog, contact, about/profile).
  // This is deliberately opt-in and additive to the backend's own DB-sourced
  // tenant context — it catches free-text content the DB fields don't model,
  // like blog article bodies or individual review comments, plus whatever a
  // tenant customizes on the page itself. Any element on the page can also
  // opt in explicitly with a `data-bb-context` attribute.
  var TENANT_CONTEXT_SELECTORS = [
    '#panel-overview', '#panel-services', '#panel-menu', '#panel-rentals',
    '#panel-reviews', '#panel-blog', '#panel-contact', '#panel-profile',
  ];

  function collectTenantPageContext() {
    var parts = [];
    TENANT_CONTEXT_SELECTORS.forEach(function (sel) {
      var el = document.querySelector(sel);
      if (!el || !isVisible(el)) return;
      var text = extractVisibleText(el, 700);
      if (text) parts.push('[' + sel.replace('#panel-', '').toUpperCase() + ']\n' + text);
    });
    document.querySelectorAll('[data-bb-context]').forEach(function (el) {
      var text = extractVisibleText(el, 500);
      if (text) parts.push('[' + (el.getAttribute('data-bb-context') || 'INFO').toUpperCase() + ']\n' + text);
    });
    return parts.join('\n\n').slice(0, 4000);
  }

  function isVisible(el) {
    return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  }

  function textOf(root, sel) {
    var el = root.querySelector(sel);
    return el ? el.textContent.trim() : '';
  }

  // Strips scripts/styles, collapses whitespace, caps length — keeps the
  // payload small and free of markup or inline JS/CSS noise.
  function extractVisibleText(root, maxLen) {
    var clone = root.cloneNode(true);
    clone.querySelectorAll('script,style,noscript,svg,button').forEach(function (n) { n.remove(); });
    var text = clone.textContent.replace(/\s+/g, ' ').trim();
    return text.slice(0, maxLen);
  }

  // ── Handoff ────────────────────────────────────────────────────────────────
  function showHandoffBar() {
    if (_handoffPending) return;
    $handoffBar.classList.add('show');
    $handoffBar.querySelectorAll('.bb-hbtn').forEach(function (b) { b.remove(); });

    var btn = document.createElement('button');
    btn.className = 'bb-hbtn wa';
    btn.innerHTML = I_WA + ' Fol me stafin';
    btn.addEventListener('click', initiateHandoff);
    $handoffBar.appendChild(btn);
  }

  function initiateHandoff() {
    _handoffPending = true;
    var name    = prompt('Emri juaj (opsionale):') || 'Vizitor';
    var contact = prompt('Email ose numër telefoni (opsionale):') || '';

    var summary = _history.slice(-6).map(function (m) {
      return (m.role === 'user' ? 'Klienti: ' : 'Bot: ') + m.content;
    }).join('\n');

    ensureFreshToken().then(function () {
      return fetch(HANDOFF_URL, {
        method:  'POST',
        headers: Object.assign({ 'Content-Type': 'application/json' }, authHeaders()),
        body:    JSON.stringify({
          tenant_slug:     _slug,
          visitor_name:    name,
          visitor_contact: contact,
          summary:         summary,
          session_id:      SESSION_ID,
        }),
      });
    })
    .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d, status: r.status }; }); })
    .then(function (res) {
      if (res.status === 401) {
        _handoffPending = false;
        showAuthGate();
        return;
      }
      // C-1 FIX: Check HTTP status before treating the response as success.
      // Without this, a 400 "invalid session" from the server (which happened
      // on every request before C-1 was fixed, because SESSION_ID was never a
      // valid signed token) caused the client to show "✅ Stafi u njoftua!"
      // and start polling — even though the server had done nothing: no CRM
      // lead, no notification, no handoff state set.
      if (!res.ok) {
        addBot('Nuk mund ta lidhim me stafin tani. Ju lutem na kontaktoni direkt.', 'err');
        _handoffPending = false;
        return;
      }
      var d = res.d;
      $handoffBar.classList.remove('show');

      // Start polling for staff direct replies
      _handoffActive = true;
      startPolling();
      setStatus('⏳ Duke pritur stafin…');

      addBot(
        '✅ Stafi u njoftua! Do t\'ju kontaktojë. Nëse doni të dërgoni mesazh direkt:', 'sys'
      );

      if (d.whatsapp_link || d.phone) {
        $handoffBar.classList.add('show');
        $handoffBar.querySelector('p').textContent = 'Kontaktoni direkt:';
        if (d.whatsapp_link) {
          var waBtn = document.createElement('button');
          waBtn.className = 'bb-hbtn wa';
          waBtn.innerHTML = I_WA + ' WhatsApp';
          waBtn.onclick = function () { window.open(d.whatsapp_link, '_blank'); };
          $handoffBar.appendChild(waBtn);
        }
        if (d.phone) {
          var phBtn = document.createElement('a');
          phBtn.className = 'bb-hbtn ph';
          phBtn.href = 'tel:' + d.phone;
          phBtn.textContent = '📞 ' + d.phone;
          $handoffBar.appendChild(phBtn);
        }
      }
    })
    .catch(function () {
      addBot('Nuk mund ta lidhem me stafin tani. Ju lutem na kontaktoni direkt.', 'err');
      _handoffPending = false;
    });
  }

  // ── Staff reply polling ────────────────────────────────────────────────────
  function startPolling() {
    if (_pollTimer) return;
    _pollTimer = setInterval(pollForStaffReply, POLL_INTERVAL_MS);
  }

  function stopPolling() {
    if (_pollTimer) {
      clearInterval(_pollTimer);
      _pollTimer = null;
    }
  }

  function pollForStaffReply() {
    if (!_handoffActive) { stopPolling(); return; }

    ensureFreshToken().then(function () {
      return fetch(POLL_URL + SESSION_ID + '/', { method: 'GET', headers: authHeaders() });
    })
      .then(function (r) {
        if (r.status === 401) {
          stopPolling();
          showAuthGate();
          return null;
        }
        return r.json();
      })
      .then(function (d) {
        if (!d) return;
        if (d.staff_reply) {
          var sr = d.staff_reply;
          // Show staff name label
          var label = document.createElement('div');
          label.className = 'bb-staff-label';
          label.textContent = '👤 ' + (sr.staff_name || 'Stafi') + (sr.staff_role ? ' — ' + sr.staff_role : '');
          $msgs.appendChild(label);

          // Show staff message with green styling
          addMsg(sr.message, 'staff', false);
          _history.push({ role: 'assistant', content: '[Staff: ' + sr.staff_name + '] ' + sr.message });

          // Show badge if window closed
          if (!_isOpen) {
            document.getElementById('bb-badge').classList.add('show');
          }
          setStatus('💬 Stafi është online');
        }
      })
      .catch(function () {
        // Silent fail — will retry on next interval
      });
  }

  // ── DOM helpers ────────────────────────────────────────────────────────────

  // addBot — used for AI replies and system messages; always textContent (XSS-safe)
  function addBot(text, extraCls) {
    return addMsg(text, 'bot' + (extraCls ? ' ' + extraCls : ''), false);
  }

  // addBotHTML — used only for trusted hardcoded strings that intentionally contain HTML
  function addBotHTML(html, extraCls) {
    return addMsg(html, 'bot' + (extraCls ? ' ' + extraCls : ''), true);
  }

  function addUser(text) {
    return addMsg(text, 'usr', false);
  }

  // useHTML must be explicitly true; defaults to safe textContent
  function addMsg(content, cls, useHTML) {
    var el = document.createElement('div');
    el.className = 'bb-m ' + cls;
    if (useHTML === true) {
      el.innerHTML = content;
    } else {
      el.textContent = content;
    }
    $msgs.appendChild(el);
    if (!_isOpen) {
      document.getElementById('bb-badge').classList.add('show');
    }
    scrollBottom();
    return el;
  }

  function addChips(chips) {
    var row = document.createElement('div');
    row.className = 'bb-chips';
    chips.forEach(function (c) {
      var btn = document.createElement('button');
      btn.className = 'bb-chip';
      btn.textContent = c.label;
      btn.addEventListener('click', function () {
        row.remove();
        sendMessage(c.msg);
      });
      row.appendChild(btn);
    });
    $msgs.appendChild(row);
    scrollBottom();
  }

  function setStatus(text) {
    if ($subTitle) $subTitle.textContent = text;
  }

  function scrollBottom() {
    if ($msgs) $msgs.scrollTop = $msgs.scrollHeight;
  }

  function esc(s) {
    return String(s)
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  // ── Public ─────────────────────────────────────────────────────────────────
  window.BizBot = { init: init };

})();
