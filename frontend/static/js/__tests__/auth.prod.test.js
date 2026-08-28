/**
 * @jest-environment jsdom
 * @jest-environment-options {"url": "https://bizal.al/"}
 *
 * auth.js on a production (non-localhost) hostname: API_BASE should be
 * same-origin (empty string), and _devTenantSlug()'s early-return branch
 * (never appends ?tenant= — the backend resolves the tenant from the real
 * subdomain instead) should be exercised.
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
});

afterEach(() => {
  delete global.fetch;
});

test('API_BASE is same-origin (empty string) on a production hostname', () => {
  const Auth = loadAuth();
  expect(Auth.API_BASE).toBe('');
});

test('apiFetch never appends ?tenant= in production, even with a tenant_slug in localStorage', async () => {
  const Auth = loadAuth();
  localStorage.setItem('tenant_slug', 'storedshop');
  global.fetch.mockResolvedValueOnce(jsonResponse(200, {}));

  await Auth.get('/things/');

  const [url] = global.fetch.mock.calls[0];
  expect(url).toBe('/api/things/');
});
