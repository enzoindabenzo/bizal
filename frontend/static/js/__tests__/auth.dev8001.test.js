/**
 * @jest-environment jsdom
 * @jest-environment-options {"url": "http://localhost:8001/"}
 *
 * auth.js tests specific to the tenant-subdomain dev setup (port 8001),
 * where API_BASE, _devTenantSlug(), and the "append ?tenant=" logic on
 * apiFetch/login all take their alternate branch.
 */

function loadAuth() {
  jest.resetModules();
  delete window.Auth;
  require('../auth.js');
  return window.Auth;
}

function jsonResponse(status, body) {
  return { ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) };
}

beforeEach(() => {
  localStorage.clear();
  global.fetch = jest.fn();
  window.history.pushState({}, '', '/');
});

afterEach(() => {
  delete global.fetch;
});

test('API_BASE uses the actual dev port (8001)', () => {
  const Auth = loadAuth();
  expect(Auth.API_BASE).toBe('http://localhost:8001');
});

test('apiFetch appends ?tenant= from the ?tenant= query param on port 8001', async () => {
  const Auth = loadAuth();
  window.history.pushState({}, '', '/?tenant=myshop');
  global.fetch.mockResolvedValueOnce(jsonResponse(200, {}));

  await Auth.get('/things/');

  const [url] = global.fetch.mock.calls[0];
  expect(url).toMatch(/[?&]tenant=myshop/);
});

test('apiFetch falls back to localStorage tenant_slug when no query param is present', async () => {
  const Auth = loadAuth();
  localStorage.setItem('tenant_slug', 'storedshop');
  global.fetch.mockResolvedValueOnce(jsonResponse(200, {}));

  await Auth.get('/things/');

  const [url] = global.fetch.mock.calls[0];
  expect(url).toMatch(/[?&]tenant=storedshop/);
});

test('apiFetch does not duplicate ?tenant= if the endpoint already has one', async () => {
  const Auth = loadAuth();
  localStorage.setItem('tenant_slug', 'storedshop');
  global.fetch.mockResolvedValueOnce(jsonResponse(200, {}));

  await Auth.get('/things/?tenant=explicit');

  const [url] = global.fetch.mock.calls[0];
  expect((url.match(/tenant=/g) || []).length).toBe(1);
  expect(url).toMatch(/tenant=explicit/);
});

test('apiFetch adds no tenant param when neither query nor localStorage has a slug', async () => {
  const Auth = loadAuth();
  global.fetch.mockResolvedValueOnce(jsonResponse(200, {}));

  await Auth.get('/things/');

  const [url] = global.fetch.mock.calls[0];
  expect(url).not.toMatch(/tenant=/);
});

test('login appends ?tenant= to the login URL on port 8001 when a dev slug is known', async () => {
  const Auth = loadAuth();
  localStorage.setItem('tenant_slug', 'storedshop');
  global.fetch.mockResolvedValueOnce(jsonResponse(200, { access: 'a', refresh: 'r' }));

  await Auth.login('x@y.com', 'pw');

  const [url] = global.fetch.mock.calls[0];
  expect(url).toMatch(/[?&]tenant=storedshop/);
});
