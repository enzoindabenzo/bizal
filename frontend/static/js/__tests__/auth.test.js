/**
 * auth.js test suite — default jsdom environment (http://localhost/, no
 * port). This exercises the "main domain" (port 8000-default) branch of
 * API_BASE and everything that doesn't depend on being on port 8001.
 *
 * auth.js is a plain top-level `const Auth = (()=>{...})()` script (no
 * module.exports) — it now assigns `window.Auth = Auth` at the bottom
 * purely for testability (same pattern as window.esc in ui.js). Each test
 * does a fresh `jest.resetModules()` + `require('../auth.js')` so the
 * module-level `_accessToken` / `_refreshPromise` state never leaks
 * between tests.
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

describe('API_BASE', () => {
  test('defaults to port 8000 on localhost with no explicit port', () => {
    const Auth = loadAuth();
    expect(Auth.API_BASE).toBe('http://localhost:8000');
  });
});

describe('legacy key scrub on load', () => {
  test('clears legacy plaintext access-token keys but leaves refresh token alone', () => {
    localStorage.setItem('bizal_access', 'old-plain-token');
    localStorage.setItem('access', 'old-plain-token-2');
    localStorage.setItem('bizal-admin-token', 'old-admin-token');
    localStorage.setItem('bizal_refresh', 'keep-me');

    loadAuth();

    expect(localStorage.getItem('bizal_access')).toBeNull();
    expect(localStorage.getItem('access')).toBeNull();
    expect(localStorage.getItem('bizal-admin-token')).toBeNull();
    expect(localStorage.getItem('bizal_refresh')).toBe('keep-me');
  });
});

describe('token storage', () => {
  test('setTokens stores access only in memory and refresh in both keys', () => {
    const Auth = loadAuth();
    Auth.setTokens('acc-1', 'ref-1');

    expect(Auth.getAccess()).toBe('acc-1');
    expect(localStorage.getItem('bizal_refresh')).toBe('ref-1');
    expect(localStorage.getItem('refresh')).toBe('ref-1');
  });

  test('setTokens with no refresh leaves stored refresh keys untouched', () => {
    const Auth = loadAuth();
    Auth.setTokens('acc-1', 'ref-1');
    Auth.setTokens('acc-2', null);

    expect(Auth.getAccess()).toBe('acc-2');
    expect(localStorage.getItem('refresh')).toBe('ref-1');
  });

  test('getRefresh falls back to the legacy "refresh" key', () => {
    const Auth = loadAuth();
    localStorage.setItem('refresh', 'legacy-ref');
    expect(Auth.getRefresh()).toBe('legacy-ref');
  });

  test('clearTokens wipes memory access token and all refresh-token keys', () => {
    const Auth = loadAuth();
    Auth.setTokens('acc-1', 'ref-1');
    Auth.clearTokens();

    expect(Auth.getAccess()).toBeNull();
    expect(Auth.getRefresh()).toBeNull();
  });

  test('isLoggedIn is true with only an access token, only a refresh token, or both; false with neither', () => {
    const Auth = loadAuth();
    expect(Auth.isLoggedIn()).toBe(false);

    Auth.setTokens('acc', null);
    expect(Auth.isLoggedIn()).toBe(true);

    Auth.clearTokens();
    localStorage.setItem('bizal_refresh', 'ref-only');
    expect(Auth.isLoggedIn()).toBe(true);
  });

  test('save/clear/headers legacy aliases behave like their modern counterparts', () => {
    const Auth = loadAuth();
    Auth.save('acc-x', 'ref-x');
    expect(Auth.getAccess()).toBe('acc-x');
    expect(Auth.headers()).toEqual({ Authorization: 'Bearer acc-x' });

    Auth.clear();
    expect(Auth.getAccess()).toBeNull();
    expect(Auth.headers()).toEqual({});
  });
});

describe('parseJWT', () => {
  test('decodes a well-formed JWT payload', () => {
    const Auth = loadAuth();
    const payload = { sub: '123', role: 'owner' };
    const b64 = Buffer.from(JSON.stringify(payload)).toString('base64')
      .replace(/\+/g, '-').replace(/\//g, '_');
    const token = `header.${b64}.sig`;
    expect(Auth.parseJWT(token)).toEqual(payload);
  });

  test('returns null for a malformed token', () => {
    const Auth = loadAuth();
    expect(Auth.parseJWT('not-a-real-jwt')).toBeNull();
  });
});

describe('refreshAccess', () => {
  test('success stores the new access (and refresh) tokens and resolves with the access token', async () => {
    const Auth = loadAuth();
    localStorage.setItem('bizal_refresh', 'ref-tok');
    global.fetch.mockResolvedValueOnce(jsonResponse(200, { access: 'new-acc', refresh: 'new-ref' }));

    const result = await Auth.refreshAccess();

    expect(result).toBe('new-acc');
    expect(Auth.getAccess()).toBe('new-acc');
    expect(localStorage.getItem('bizal_refresh')).toBe('new-ref');
  });

  test('rejects immediately with no refresh token, never calling fetch', async () => {
    const Auth = loadAuth();
    await expect(Auth.refreshAccess()).rejects.toThrow('no_refresh');
    expect(global.fetch).not.toHaveBeenCalled();
  });

  test('a failed refresh response clears tokens and rejects', async () => {
    const Auth = loadAuth();
    localStorage.setItem('bizal_refresh', 'ref-tok');
    global.fetch.mockResolvedValueOnce(jsonResponse(401, {}));

    await expect(Auth.refreshAccess()).rejects.toThrow('refresh_failed');
    expect(Auth.getRefresh()).toBeNull();
  });

  test('concurrent calls share the same in-flight refresh (fetch called once)', async () => {
    const Auth = loadAuth();
    localStorage.setItem('bizal_refresh', 'ref-tok');
    let resolveFetch;
    global.fetch.mockReturnValueOnce(new Promise(res => { resolveFetch = res; }));

    const p1 = Auth.refreshAccess();
    const p2 = Auth.refreshAccess();
    resolveFetch(jsonResponse(200, { access: 'shared-acc' }));
    const [r1, r2] = await Promise.all([p1, p2]);

    expect(r1).toBe('shared-acc');
    expect(r2).toBe('shared-acc');
    expect(global.fetch).toHaveBeenCalledTimes(1);
  });
});

describe('apiFetch', () => {
  test('attaches Authorization header when an access token is present', async () => {
    const Auth = loadAuth();
    Auth.setTokens('acc-tok', 'ref-tok');
    global.fetch.mockResolvedValueOnce(jsonResponse(200, {}));

    await Auth.get('/things/');

    const [, opts] = global.fetch.mock.calls[0];
    expect(opts.headers.Authorization).toBe('Bearer acc-tok');
    expect(opts.method).toBe('GET');
  });

  test('with no in-memory token but a stored refresh token, silently refreshes before the request', async () => {
    const Auth = loadAuth();
    localStorage.setItem('bizal_refresh', 'ref-tok');
    global.fetch
      .mockResolvedValueOnce(jsonResponse(200, { access: 'restored-acc' })) // refreshAccess
      .mockResolvedValueOnce(jsonResponse(200, { ok: true }));              // actual request

    await Auth.get('/things/');

    expect(global.fetch).toHaveBeenCalledTimes(2);
    const [, opts] = global.fetch.mock.calls[1];
    expect(opts.headers.Authorization).toBe('Bearer restored-acc');
  });

  test('with no token at all, proceeds without Authorization header (will 401 downstream)', async () => {
    const Auth = loadAuth();
    global.fetch.mockResolvedValueOnce(jsonResponse(200, {}));

    await Auth.get('/things/');

    const [, opts] = global.fetch.mock.calls[0];
    expect(opts.headers.Authorization).toBeUndefined();
  });

  test('serializes a plain object body to JSON with a Content-Type header', async () => {
    const Auth = loadAuth();
    global.fetch.mockResolvedValueOnce(jsonResponse(200, {}));

    await Auth.post('/things/', { a: 1 });

    const [, opts] = global.fetch.mock.calls[0];
    expect(opts.headers['Content-Type']).toBe('application/json');
    expect(opts.body).toBe('{"a":1}');
  });

  test('leaves a string body as-is', async () => {
    const Auth = loadAuth();
    global.fetch.mockResolvedValueOnce(jsonResponse(200, {}));

    await Auth.post('/things/', 'raw-string-body');

    const [, opts] = global.fetch.mock.calls[0];
    expect(opts.body).toBe('raw-string-body');
  });

  test('FormData bodies skip Content-Type and are passed through untouched', async () => {
    const Auth = loadAuth();
    global.fetch.mockResolvedValueOnce(jsonResponse(200, {}));
    const fd = new FormData();
    fd.append('file', 'x');

    await Auth.post('/upload/', fd);

    const [, opts] = global.fetch.mock.calls[0];
    expect(opts.headers['Content-Type']).toBeUndefined();
    expect(opts.body).toBe(fd);
  });

  test('a 401 triggers exactly one silent refresh + retry, then returns the retried response', async () => {
    const Auth = loadAuth();
    Auth.setTokens('stale-acc', 'ref-tok');
    global.fetch
      .mockResolvedValueOnce(jsonResponse(401, {}))
      .mockResolvedValueOnce(jsonResponse(200, { access: 'fresh-acc' }))
      .mockResolvedValueOnce(jsonResponse(200, { data: 'ok' }));

    const r = await Auth.get('/things/');

    expect(global.fetch).toHaveBeenCalledTimes(3);
    const [, retryOpts] = global.fetch.mock.calls[2];
    expect(retryOpts.headers.Authorization).toBe('Bearer fresh-acc');
    expect((await r.json()).data).toBe('ok');
  });

  test('a 401 with a failed refresh clears tokens and navigates to "/" instead of retrying forever', async () => {
    const Auth = loadAuth();
    Auth.setTokens('stale-acc', 'ref-tok');
    global.fetch
      .mockResolvedValueOnce(jsonResponse(401, {}))
      .mockResolvedValueOnce(jsonResponse(401, {})); // refresh attempt also fails

    await Auth.get('/things/');

    expect(global.fetch).toHaveBeenCalledTimes(2);
    expect(Auth.getAccess()).toBeNull();
  });

  test('does not retry a second time (retry=false path returns the 401 response directly)', async () => {
    const Auth = loadAuth();
    // No refresh token available at all -> apiFetch's initial "restore" skip,
    // then the request itself 401s, retry() is attempted and immediately
    // rejects with no_refresh, landing on the clearTokens+navigate branch
    // without ever calling fetch a second time.
    global.fetch.mockResolvedValueOnce(jsonResponse(401, {}));

    await Auth.get('/things/');

    expect(global.fetch).toHaveBeenCalledTimes(1);
  });

  test('get/patch/put/del helpers pass through the right HTTP method', async () => {
    const Auth = loadAuth();
    global.fetch.mockResolvedValue(jsonResponse(200, {}));

    await Auth.patch('/x/', { a: 1 });
    await Auth.put('/x/', { a: 1 });
    await Auth.del('/x/');

    const methods = global.fetch.mock.calls.map(c => c[1].method);
    expect(methods).toEqual(['PATCH', 'PUT', 'DELETE']);
  });
});

describe('login', () => {
  test('success stores tokens and returns the response body', async () => {
    const Auth = loadAuth();
    global.fetch.mockResolvedValueOnce(jsonResponse(200, { access: 'a', refresh: 'r', email: 'x@y.com' }));

    const d = await Auth.login('x@y.com', 'pw');

    expect(d.email).toBe('x@y.com');
    expect(Auth.getAccess()).toBe('a');
  });

  test('failure surfaces the backend detail message', async () => {
    const Auth = loadAuth();
    global.fetch.mockResolvedValueOnce(jsonResponse(400, { detail: 'Bad credentials' }));

    await expect(Auth.login('x@y.com', 'wrong')).rejects.toThrow('Bad credentials');
  });

  test('failure falls back to non_field_errors, then to a generic Albanian message', async () => {
    const Auth = loadAuth();
    global.fetch.mockResolvedValueOnce(jsonResponse(400, { non_field_errors: ['Nope'] }));
    await expect(Auth.login('x@y.com', 'wrong')).rejects.toThrow('Nope');

    global.fetch.mockResolvedValueOnce(jsonResponse(400, {}));
    await expect(Auth.login('x@y.com', 'wrong')).rejects.toThrow(/gabuara/);
  });

  test('a 403 with redirect_slug attaches it to the thrown error', async () => {
    const Auth = loadAuth();
    global.fetch.mockResolvedValueOnce(jsonResponse(403, { detail: 'Wrong domain', redirect_slug: 'myshop' }));

    try {
      await Auth.login('x@y.com', 'pw');
      throw new Error('should have thrown');
    } catch (err) {
      expect(err.redirectSlug).toBe('myshop');
    }
  });
});

describe('logout', () => {
  test('with a refresh token, calls the logout endpoint then clears tokens and navigates', async () => {
    const Auth = loadAuth();
    Auth.setTokens('acc', 'ref-tok');
    global.fetch.mockResolvedValue(jsonResponse(200, {}));

    await Auth.logout('/goodbye');

    expect(global.fetch).toHaveBeenCalled();
    expect(Auth.getAccess()).toBeNull();
  });

  test('with no refresh token, skips the network call and still clears + navigates', async () => {
    const Auth = loadAuth();
    await Auth.logout('/goodbye');
    expect(global.fetch).not.toHaveBeenCalled();
  });

  test('a failed logout call is swallowed and cleanup still happens', async () => {
    const Auth = loadAuth();
    Auth.setTokens('acc', 'ref-tok');
    global.fetch.mockRejectedValue(new Error('network down'));

    await expect(Auth.logout()).resolves.toBeUndefined();
    expect(Auth.getAccess()).toBeNull();
  });
});

describe('pickupTokensFromUrl', () => {
  test('reads access/refresh tokens from the query string, stores them, and strips them from the URL', () => {
    const Auth = loadAuth();
    window.history.pushState({}, '', '/account.html?access_token=abc&refresh_token=def&keep=1');

    Auth.pickupTokensFromUrl();

    expect(Auth.getAccess()).toBe('abc');
    expect(window.location.search).not.toMatch(/access_token/);
    expect(window.location.search).toMatch(/keep=1/);
  });

  test('is a no-op when there is no access_token param', () => {
    const Auth = loadAuth();
    window.history.pushState({}, '', '/account.html?foo=bar');

    Auth.pickupTokensFromUrl();

    expect(Auth.getAccess()).toBeNull();
    expect(window.location.search).toBe('?foo=bar');
  });
});

describe('me', () => {
  test('returns the parsed user on success', async () => {
    const Auth = loadAuth();
    global.fetch.mockResolvedValueOnce(jsonResponse(200, { id: 1, email: 'a@b.com' }));
    const user = await Auth.me();
    expect(user).toEqual({ id: 1, email: 'a@b.com' });
  });

  test('returns null on a non-ok response', async () => {
    const Auth = loadAuth();
    global.fetch.mockResolvedValueOnce(jsonResponse(401, {}));
    expect(await Auth.me()).toBeNull();
  });
});

describe('_devTenantSlug via apiFetch on localhost (default port, not 8001)', () => {
  test('does not append ?tenant= when not on port 8001, even with a query param present', async () => {
    const Auth = loadAuth();
    window.history.pushState({}, '', '/?tenant=myshop');
    global.fetch.mockResolvedValueOnce(jsonResponse(200, {}));

    await Auth.get('/things/');

    const [url] = global.fetch.mock.calls[0];
    expect(url).not.toMatch(/tenant=/);
  });
});
