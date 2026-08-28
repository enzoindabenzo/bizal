/**
 * BizBot widget auth-gate tests.
 *
 * chatbot.js is a plain IIFE that only exposes `window.BizBot.init()` — there
 * is no exported internals to unit-test directly, so these tests drive the
 * real widget the way a browser would: init() it in jsdom, type into the
 * real <textarea>, click the real send button, and assert on the real fetch
 * calls + DOM output. This is the only way to exercise ensureFreshToken()'s
 * silent-refresh-and-retry path and confirm it never falls back to
 * Auth.apiFetch()'s "navigate to /" behavior.
 *
 * `Auth` and `fetch` are both bare globals as far as chatbot.js is
 * concerned (same as in the browser), so we stub them on `global` before
 * each require.
 */

const CHAT_URL = '/api/chatbot/chat/';

function makeAuth(overrides = {}) {
  const defaults = {
    loggedIn: true,
    access: 'access-tok',
    refresh: 'refresh-tok',
  };
  const cfg = Object.assign({}, defaults, overrides);
  return {
    isLoggedIn:    jest.fn(() => cfg.loggedIn),
    getAccess:     jest.fn(() => cfg.access),
    getRefresh:    jest.fn(() => cfg.refresh),
    headers:       jest.fn(() => (cfg.access ? { Authorization: 'Bearer ' + cfg.access } : {})),
    refreshAccess: cfg.refreshAccess || jest.fn(() => Promise.resolve()),
  };
}

/** Load a fresh copy of chatbot.js against a clean document + fresh globals,
 * then init() the widget. Returns the Auth stub used, for assertions. */
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

/** Drain the microtask queue enough times for chatbot.js's chained
 * .then()s (ensureFreshToken -> fetch -> json -> handling, plus the
 * one-retry branch) to fully settle. */
async function flush(times = 15) {
  for (let i = 0; i < times; i++) {
    await Promise.resolve();
  }
}

function jsonResponse(status, body) {
  return { ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) };
}

describe('BizBot auth gate', () => {
  const startingHref = window.location.href;

  afterEach(() => {
    delete global.Auth;
    delete global.fetch;
  });

  test('anonymous visitor sees the auth gate and no request is ever sent', () => {
    const auth = loadWidget({}, { loggedIn: false });

    expect(document.getElementById('bb-inp').disabled).toBe(true);
    expect(botMessages().join(' ')).toMatch(/identifikoheni/i);

    typeAndSend('a real question');

    expect(global.fetch).not.toHaveBeenCalled();
    expect(auth.isLoggedIn).toHaveBeenCalled();
  });

  test('anonymous visitor on a tenant storefront also gets gated, no request sent', () => {
    loadWidget({ slug: 'myshop', name: 'My Shop' }, { loggedIn: false });

    expect(document.getElementById('bb-inp').disabled).toBe(true);
    typeAndSend('what are your hours');

    expect(global.fetch).not.toHaveBeenCalled();
  });

  test('authenticated visitor on the main domain: bearer token attached, reply rendered', async () => {
    const auth = loadWidget({}, { access: 'main-tok' });
    global.fetch.mockResolvedValueOnce(
      jsonResponse(200, { reply: 'We have three plans.', handoff_hint: false })
    );

    typeAndSend('What plans do you have?');
    await flush();

    expect(global.fetch).toHaveBeenCalledTimes(1);
    const [url, opts] = global.fetch.mock.calls[0];
    expect(url).toBe(CHAT_URL);
    expect(opts.headers.Authorization).toBe('Bearer main-tok');
    expect(JSON.parse(opts.body).tenant_slug).toBeUndefined();
    expect(botMessages()).toContain('We have three plans.');
  });

  test('authenticated visitor on a tenant storefront: tenant_slug included, reply rendered', async () => {
    loadWidget({ slug: 'myshop', name: 'My Shop' }, { access: 'tenant-tok' });
    global.fetch.mockResolvedValueOnce(
      jsonResponse(200, { reply: 'We are open 9 to 5.', handoff_hint: false })
    );

    typeAndSend('What are your hours?');
    await flush();

    expect(global.fetch).toHaveBeenCalledTimes(1);
    const [, opts] = global.fetch.mock.calls[0];
    expect(opts.headers.Authorization).toBe('Bearer tenant-tok');
    expect(JSON.parse(opts.body).tenant_slug).toBe('myshop');
    expect(botMessages()).toContain('We are open 9 to 5.');
  });

  test('missing in-memory access token: ensureFreshToken silently refreshes before the first request', async () => {
    const refreshAccess = jest.fn(() => Promise.resolve());
    loadWidget({}, { access: null, refresh: 'reftok', refreshAccess });
    global.fetch.mockResolvedValueOnce(jsonResponse(200, { reply: 'ok' }));

    typeAndSend('hello');
    await flush();

    expect(refreshAccess).toHaveBeenCalledTimes(1);
    expect(global.fetch).toHaveBeenCalledTimes(1);
  });

  test('expired token: a 401 triggers exactly one silent refresh + retry, then succeeds', async () => {
    const refreshAccess = jest.fn(() => Promise.resolve());
    loadWidget({}, { refreshAccess });

    global.fetch
      .mockResolvedValueOnce(jsonResponse(401, {}))
      .mockResolvedValueOnce(jsonResponse(200, { reply: 'Back online.' }));

    typeAndSend('are you there');
    await flush();

    expect(global.fetch).toHaveBeenCalledTimes(2);
    expect(refreshAccess).toHaveBeenCalledTimes(1);
    expect(botMessages()).toContain('Back online.');
    // Never falls back to Auth.apiFetch()'s navigate-away behavior.
    expect(window.location.href).toBe(startingHref);
  });

  test('expired token and failed refresh: widget locks in place, no navigation, no infinite retry', async () => {
    const refreshAccess = jest.fn(() => Promise.reject(new Error('refresh failed')));
    loadWidget({}, { refreshAccess });

    global.fetch.mockResolvedValueOnce(jsonResponse(401, {}));

    typeAndSend('are you there');
    await flush();

    expect(global.fetch).toHaveBeenCalledTimes(1);
    expect(refreshAccess).toHaveBeenCalledTimes(1);
    expect(document.getElementById('bb-inp').disabled).toBe(true);
    expect(botMessages().join(' ')).toMatch(/identifikoheni/i);
    expect(window.location.href).toBe(startingHref);
  });

  test('401 with no refresh token available: locks immediately, never retries', async () => {
    loadWidget({}, { refresh: null });
    global.fetch.mockResolvedValueOnce(jsonResponse(401, {}));

    typeAndSend('are you there');
    await flush();

    expect(global.fetch).toHaveBeenCalledTimes(1);
    expect(document.getElementById('bb-inp').disabled).toBe(true);
    expect(window.location.href).toBe(startingHref);
  });

  test('401 with failed refresh on a tenant storefront also locks without navigating', async () => {
    const refreshAccess = jest.fn(() => Promise.reject(new Error('nope')));
    loadWidget({ slug: 'myshop', name: 'My Shop' }, { refreshAccess });
    global.fetch.mockResolvedValueOnce(jsonResponse(401, {}));

    typeAndSend('are you there');
    await flush();

    expect(global.fetch).toHaveBeenCalledTimes(1);
    expect(document.getElementById('bb-inp').disabled).toBe(true);
    expect(window.location.href).toBe(startingHref);
  });
});
