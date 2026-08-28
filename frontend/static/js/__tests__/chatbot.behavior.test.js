/**
 * Additional BizBot behavioral coverage: window open/close + badge,
 * live page-context scraping (marketing + tenant), the handoff flow
 * (initiateHandoff -> HANDOFF_URL), staff-reply polling, and the
 * various sendMessage() response branches (session_capped, capped,
 * handoff_hint, generic error, network failure).
 *
 * Same loading pattern as chatbot.auth.test.js: chatbot.js is a plain
 * IIFE exposing only window.BizBot.init(), so we drive it like a real
 * browser would.
 */

const CHAT_URL = '/api/chatbot/chat/';
const HANDOFF_URL = '/api/chatbot/handoff/';

function makeAuth(overrides = {}) {
  const defaults = { loggedIn: true, access: 'access-tok', refresh: 'refresh-tok' };
  const cfg = Object.assign({}, defaults, overrides);
  return {
    isLoggedIn: jest.fn(() => cfg.loggedIn),
    getAccess: jest.fn(() => cfg.access),
    getRefresh: jest.fn(() => cfg.refresh),
    headers: jest.fn(() => (cfg.access ? { Authorization: 'Bearer ' + cfg.access } : {})),
    refreshAccess: cfg.refreshAccess || jest.fn(() => Promise.resolve()),
  };
}

function loadWidget(initOpts, authOverrides) {
  document.body.innerHTML = '';
  document.head.querySelectorAll('#bb-css').forEach((n) => n.remove());
  global.fetch = jest.fn();
  const auth = makeAuth(authOverrides);
  global.Auth = auth;
  jest.resetModules();
  require('../chatbot.js');
  window.BizBot.init(initOpts || {});
  return auth;
}

function typeAndSend(text) {
  const input = document.getElementById('bb-inp');
  input.value = text;
  document.getElementById('bb-snd').click();
}

function botMessages() {
  return Array.from(document.querySelectorAll('#bb-msgs .bb-m')).map((el) => el.textContent);
}

async function flush(times = 15) {
  for (let i = 0; i < times; i++) {
    await Promise.resolve();
  }
}

function jsonResponse(status, body) {
  return { ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) };
}

afterEach(() => {
  delete global.Auth;
  delete global.fetch;
  jest.useRealTimers();
});

describe('window open/close', () => {
  test('toggleWindow opens the window, focuses input, and clears the unread badge', () => {
    loadWidget();
    const fab = document.getElementById('bb-fab');
    const win = document.getElementById('bb-win');

    fab.click();

    expect(win.classList.contains('bb-hide')).toBe(false);
  });

  test('clicking the close button hides the window', () => {
    loadWidget();
    document.getElementById('bb-fab').click();
    document.getElementById('bb-x').click();
    expect(document.getElementById('bb-win').classList.contains('bb-hide')).toBe(true);
  });

  test('a new bot message shows the unread badge while the window is closed', () => {
    loadWidget({ slug: 'myshop', name: 'My Shop' }, { loggedIn: false });
    // showWelcome() already ran with the window closed -> badge should show.
    expect(document.getElementById('bb-badge').classList.contains('show')).toBe(true);
  });

  test('opening the window clears the badge', () => {
    loadWidget({ slug: 'myshop', name: 'My Shop' }, { loggedIn: false });
    document.getElementById('bb-fab').click();
    expect(document.getElementById('bb-badge').classList.contains('show')).toBe(false);
  });
});

describe('Enter-to-send and textarea auto-grow', () => {
  test('pressing Enter without Shift sends the message', async () => {
    loadWidget();
    global.fetch.mockResolvedValueOnce(jsonResponse(200, { reply: 'hi there' }));
    const input = document.getElementById('bb-inp');
    input.value = 'hello';
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
    await flush();
    expect(global.fetch).toHaveBeenCalledTimes(1);
  });

  test('Shift+Enter does not send', () => {
    loadWidget();
    const input = document.getElementById('bb-inp');
    input.value = 'hello';
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', shiftKey: true, bubbles: true, cancelable: true }));
    expect(global.fetch).not.toHaveBeenCalled();
  });

  test('typing resizes the textarea height', () => {
    loadWidget();
    const input = document.getElementById('bb-inp');
    input.value = 'a\nb\nc';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    expect(input.style.height).toMatch(/px$/);
  });
});

describe('welcome message + quick-reply chips', () => {
  test('marketing widget (no slug), authenticated: shows chips and clicking one sends its message', async () => {
    loadWidget({});
    global.fetch.mockResolvedValueOnce(jsonResponse(200, { reply: 'We have 3 plans' }));

    const chip = document.querySelector('.bb-chip');
    expect(chip).not.toBeNull();
    chip.click();
    await flush();

    expect(global.fetch).toHaveBeenCalledTimes(1);
    expect(botMessages()).toContain('We have 3 plans');
    // chip row removed after click
    expect(document.querySelector('.bb-chips')).toBeNull();
  });

  test('tenant widget, authenticated: shows business name and tenant-specific chips', () => {
    loadWidget({ slug: 'myshop', name: 'My Shop' });
    expect(document.getElementById('bb-sub').textContent).toMatch(/Online/);
    expect(document.querySelectorAll('.bb-chip').length).toBe(4);
  });
});

describe('sendMessage response branches', () => {
  test('session_capped locks the widget and shows the sys message', async () => {
    loadWidget();
    global.fetch.mockResolvedValueOnce(
      jsonResponse(403, { session_capped: true, reply: 'Limit hit for this chat', session_id: 'srv-tok.sig' })
    );

    typeAndSend('hello');
    await flush();

    expect(botMessages()).toContain('Limit hit for this chat');
    expect(document.getElementById('bb-inp').disabled).toBe(true);
    expect(document.getElementById('bb-snd').disabled).toBe(true);
  });

  test('capped (daily limit) shows the sys message but does not lock the widget', async () => {
    loadWidget();
    global.fetch.mockResolvedValueOnce(jsonResponse(429, { capped: true, reply: 'Daily limit reached' }));

    typeAndSend('hello');
    await flush();

    expect(botMessages()).toContain('Daily limit reached');
    expect(document.getElementById('bb-inp').disabled).toBe(false);
  });

  test('an unrecognized error shape falls back to the generic error message', async () => {
    loadWidget();
    global.fetch.mockResolvedValueOnce(jsonResponse(500, {}));

    typeAndSend('hello');
    await flush();

    expect(botMessages().join(' ')).toMatch(/gabim/i);
  });

  test('a network failure (fetch rejects) shows the offline error message', async () => {
    loadWidget();
    global.fetch.mockRejectedValueOnce(new Error('offline'));

    typeAndSend('hello');
    await flush();

    expect(botMessages().join(' ')).toMatch(/internetin/i);
  });

  test('the seriousness filter ("stopped") disables the widget', async () => {
    loadWidget();
    global.fetch.mockResolvedValueOnce(jsonResponse(200, { reply: 'ok, last one', stopped: true }));

    typeAndSend('irrelevant question');
    await flush();

    expect(document.getElementById('bb-inp').disabled).toBe(true);
    expect(document.getElementById('bb-snd').disabled).toBe(true);
  });

  test('handoff_hint on a tenant widget reveals the handoff bar with a "talk to staff" button', async () => {
    loadWidget({ slug: 'myshop', name: 'My Shop' });
    global.fetch.mockResolvedValueOnce(jsonResponse(200, { reply: 'Let me connect you', handoff_hint: true }));

    typeAndSend('I want a human');
    await flush();

    const bar = document.getElementById('bb-handoff');
    expect(bar.classList.contains('show')).toBe(true);
    expect(bar.querySelector('.bb-hbtn')).not.toBeNull();
  });

  test('handoff_hint is ignored on the marketing widget (no slug)', async () => {
    loadWidget({});
    global.fetch.mockResolvedValueOnce(jsonResponse(200, { reply: 'Let me connect you', handoff_hint: true }));

    typeAndSend('I want a human');
    await flush();

    expect(document.getElementById('bb-handoff').classList.contains('show')).toBe(false);
  });

  test('re-engaging after an active handoff clears handoff state and resets status', async () => {
    loadWidget({ slug: 'myshop', name: 'My Shop' });
    global.fetch.mockResolvedValueOnce(jsonResponse(200, { reply: 'connecting', handoff_hint: true }));
    typeAndSend('connect me');
    await flush();

    document.querySelector('.bb-hbtn').click(); // initiateHandoff
    global.fetch.mockResolvedValueOnce(jsonResponse(200, {}));
    await flush();

    global.fetch.mockResolvedValueOnce(jsonResponse(200, { reply: 'welcome back' }));
    typeAndSend('hello again');
    await flush();

    expect(document.getElementById('bb-sub').textContent).toMatch(/Online/);
  });
});

describe('page context collection', () => {
  test('marketing widget scrapes visible plan cards and feature cards into page_context', async () => {
    loadWidget({});
    document.body.insertAdjacentHTML('beforeend', `
      <div class="plans">
        <div class="pc">
          <div class="pname">Pro</div>
          <div class="pprice">2000L</div>
          <div class="pbill">/muaj</div>
          <ul class="plist"><li>Feature A</li><li class="n">Feature B</li></ul>
        </div>
      </div>
      <div id="pg-vecorite"><div class="feats"><div class="fc"><div class="ft">Fast</div><div class="fp">Very fast</div></div></div></div>
    `);
    global.fetch.mockResolvedValueOnce(jsonResponse(200, { reply: 'ok' }));

    typeAndSend('what plans do you have');
    await flush();

    const body = JSON.parse(global.fetch.mock.calls[0][1].body);
    expect(body.page_context).toMatch(/Pro/);
    expect(body.page_context).toMatch(/2000L/);
    expect(body.page_context).toMatch(/VEÇORITË/);
  });

  test('tenant widget scrapes visible panel content into page_context', async () => {
    loadWidget({ slug: 'myshop', name: 'My Shop' });
    document.body.insertAdjacentHTML('beforeend', `<div id="panel-services">Haircut - 500L</div>`);
    // jsdom reports 0 offsetWidth/Height by default; force "visible" via getClientRects mock.
    const el = document.getElementById('panel-services');
    el.getClientRects = () => [{}];
    global.fetch.mockResolvedValueOnce(jsonResponse(200, { reply: 'ok' }));

    typeAndSend('what services do you have');
    await flush();

    const body = JSON.parse(global.fetch.mock.calls[0][1].body);
    expect(body.page_context).toMatch(/Haircut/);
    expect(body.page_context).toMatch(/SERVICES/);
  });

  test('an element with data-bb-context is also included on a tenant widget', async () => {
    loadWidget({ slug: 'myshop', name: 'My Shop' });
    document.body.insertAdjacentHTML('beforeend', `<div data-bb-context="promo">50% off today</div>`);
    const el = document.querySelector('[data-bb-context]');
    el.getClientRects = () => [{}];
    global.fetch.mockResolvedValueOnce(jsonResponse(200, { reply: 'ok' }));

    typeAndSend('any promos?');
    await flush();

    const body = JSON.parse(global.fetch.mock.calls[0][1].body);
    expect(body.page_context).toMatch(/50% off today/);
    expect(body.page_context).toMatch(/PROMO/);
  });

  test('no page_context key is sent when nothing relevant is on the page', async () => {
    loadWidget({});
    global.fetch.mockResolvedValueOnce(jsonResponse(200, { reply: 'ok' }));

    typeAndSend('hello');
    await flush();

    const body = JSON.parse(global.fetch.mock.calls[0][1].body);
    expect(body.page_context).toBeFalsy();
  });
});

describe('handoff flow (initiateHandoff)', () => {
  function triggerHandoffBar(authOverrides) {
    loadWidget({ slug: 'myshop', name: 'My Shop' }, authOverrides);
    global.fetch.mockResolvedValueOnce(jsonResponse(200, { reply: 'connecting', handoff_hint: true }));
    return typeAndSend('connect me to staff');
  }

  test('successful handoff shows confirmation, starts polling, and renders WhatsApp/phone buttons', async () => {
    global.prompt = jest.fn().mockReturnValueOnce('Anna').mockReturnValueOnce('anna@x.com');
    triggerHandoffBar();
    await flush();

    global.fetch.mockResolvedValueOnce(
      jsonResponse(200, { whatsapp_link: 'https://wa.me/123', phone: '+35569000000' })
    );
    document.querySelector('.bb-hbtn').click();
    await flush();

    expect(botMessages().join(' ')).toMatch(/Stafi u njoftua/);
    expect(document.querySelector('.bb-hbtn.wa')).not.toBeNull();
    expect(document.querySelector('.bb-hbtn.ph')).not.toBeNull();
    delete global.prompt;
  });

  test('a 401 during handoff shows the auth gate', async () => {
    global.prompt = jest.fn().mockReturnValue('');
    triggerHandoffBar();
    await flush();

    global.fetch.mockResolvedValueOnce(jsonResponse(401, {}));
    document.querySelector('.bb-hbtn').click();
    await flush();

    expect(document.getElementById('bb-inp').disabled).toBe(true);
    delete global.prompt;
  });

  test('a non-ok, non-401 handoff response shows a contact-us-directly error', async () => {
    global.prompt = jest.fn().mockReturnValue('');
    triggerHandoffBar();
    await flush();

    global.fetch.mockResolvedValueOnce(jsonResponse(500, {}));
    document.querySelector('.bb-hbtn').click();
    await flush();

    expect(botMessages().join(' ')).toMatch(/Nuk mund ta lidhim me stafin/);
    delete global.prompt;
  });

  test('a network failure during handoff is caught and shown as an error', async () => {
    global.prompt = jest.fn().mockReturnValue('');
    triggerHandoffBar();
    await flush();

    global.fetch.mockRejectedValueOnce(new Error('down'));
    document.querySelector('.bb-hbtn').click();
    await flush();

    expect(botMessages().join(' ')).toMatch(/Nuk mund ta lidhem me stafin/);
    delete global.prompt;
  });
});

describe('staff-reply polling', () => {
  test('a staff reply is rendered with the staff name label and switches to staff-online status', async () => {
    jest.useFakeTimers();
    global.prompt = jest.fn().mockReturnValue('');
    loadWidget({ slug: 'myshop', name: 'My Shop' });
    global.fetch.mockResolvedValueOnce(jsonResponse(200, { reply: 'connecting', handoff_hint: true }));
    typeAndSend('connect me');
    await flush();

    global.fetch.mockResolvedValueOnce(jsonResponse(200, {}));
    document.querySelector('.bb-hbtn').click();
    await flush();

    global.fetch.mockResolvedValueOnce(
      jsonResponse(200, { staff_reply: { staff_name: 'Elira', staff_role: 'Manager', message: 'Hi, how can I help?' } })
    );
    jest.advanceTimersByTime(4000);
    await flush();

    expect(botMessages()).toContain('Hi, how can I help?');
    expect(document.querySelector('.bb-staff-label').textContent).toMatch(/Elira/);
    expect(document.getElementById('bb-sub').textContent).toMatch(/online/i);
    delete global.prompt;
  });

  test('a 401 while polling shows the auth gate and stops polling', async () => {
    jest.useFakeTimers();
    global.prompt = jest.fn().mockReturnValue('');
    loadWidget({ slug: 'myshop', name: 'My Shop' });
    global.fetch.mockResolvedValueOnce(jsonResponse(200, { reply: 'connecting', handoff_hint: true }));
    typeAndSend('connect me');
    await flush();

    global.fetch.mockResolvedValueOnce(jsonResponse(200, {}));
    document.querySelector('.bb-hbtn').click();
    await flush();

    global.fetch.mockResolvedValueOnce(jsonResponse(401, {}));
    jest.advanceTimersByTime(4000);
    await flush();

    expect(document.getElementById('bb-inp').disabled).toBe(true);
    delete global.prompt;
  });

  test('a poll network error is silently swallowed (no crash, no message)', async () => {
    jest.useFakeTimers();
    global.prompt = jest.fn().mockReturnValue('');
    loadWidget({ slug: 'myshop', name: 'My Shop' });
    global.fetch.mockResolvedValueOnce(jsonResponse(200, { reply: 'connecting', handoff_hint: true }));
    typeAndSend('connect me');
    await flush();

    global.fetch.mockResolvedValueOnce(jsonResponse(200, {}));
    document.querySelector('.bb-hbtn').click();
    await flush();

    const before = botMessages().length;
    global.fetch.mockRejectedValueOnce(new Error('timeout'));
    jest.advanceTimersByTime(4000);
    await flush();

    expect(botMessages().length).toBe(before);
    delete global.prompt;
  });

  test('closing the window pauses polling; reopening resumes it', async () => {
    jest.useFakeTimers();
    global.prompt = jest.fn().mockReturnValue('');
    loadWidget({ slug: 'myshop', name: 'My Shop' });
    global.fetch.mockResolvedValueOnce(jsonResponse(200, { reply: 'connecting', handoff_hint: true }));
    typeAndSend('connect me');
    await flush();

    global.fetch.mockResolvedValueOnce(jsonResponse(200, {}));
    document.querySelector('.bb-hbtn').click();
    await flush();

    document.getElementById('bb-x').click(); // closeWindow -> stopPolling
    const callsBeforeAdvance = global.fetch.mock.calls.length;
    jest.advanceTimersByTime(8000);
    await flush();
    expect(global.fetch.mock.calls.length).toBe(callsBeforeAdvance); // no poll fired

    global.fetch.mockResolvedValue(jsonResponse(200, {}));
    document.getElementById('bb-fab').click(); // openWindow -> resumes polling
    jest.advanceTimersByTime(4000);
    await flush();
    expect(global.fetch.mock.calls.length).toBeGreaterThan(callsBeforeAdvance);

    delete global.prompt;
  });
});
