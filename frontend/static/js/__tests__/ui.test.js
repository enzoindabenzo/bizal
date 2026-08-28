/**
 * ui.js test suite. ui.js is a plain top-level script (no module.exports);
 * it now also assigns window.Theme / window.toast / window.Modal /
 * window.showConfirm / window.parseJWT / window.fmtDate / window.fmtDateTime
 * / window.fmtALL / window.fmtEUR / window.showFeedback / window.hideFeedback
 * / window.debounce for testability, matching the pre-existing window.esc
 * pattern.
 */

function loadUi() {
  document.body.innerHTML = '';
  document.documentElement.removeAttribute('data-theme');
  localStorage.clear();
  jest.resetModules();
  [
    'Theme', 'toast', 'Modal', 'showConfirm', 'esc', 'escHtml', 'parseJWT',
    'fmtDate', 'fmtDateTime', 'fmtALL', 'fmtEUR', 'showFeedback', 'hideFeedback', 'debounce',
  ].forEach(k => delete window[k]);
  require('../ui.js');
}

beforeEach(() => {
  loadUi();
});

describe('Theme', () => {
  test('defaults to light and init() applies it to the DOM', () => {
    window.Theme.init();
    expect(document.documentElement.getAttribute('data-theme')).toBe('light');
    expect(window.Theme.current()).toBe('light');
  });

  test('toggle flips between light and dark and persists to localStorage', () => {
    window.Theme.init();
    window.Theme.toggle();
    expect(window.Theme.current()).toBe('dark');
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    expect(localStorage.getItem('bizal-theme')).toBe('dark');

    window.Theme.toggle();
    expect(window.Theme.current()).toBe('light');
  });

  test('picks up a previously stored theme on load', () => {
    localStorage.setItem('bizal-theme', 'dark');
    jest.resetModules();
    delete window.Theme;
    require('../ui.js');
    window.Theme.init();
    expect(window.Theme.current()).toBe('dark');
  });

  test('updates any [data-theme-toggle] button label/title', () => {
    const btn = document.createElement('button');
    btn.setAttribute('data-theme-toggle', '');
    document.body.appendChild(btn);

    window.Theme.init();
    expect(btn.textContent).toBe('☾');
    expect(btn.title).toBe('Dark mode');

    window.Theme.toggle();
    expect(btn.textContent).toBe('☀');
    expect(btn.title).toBe('Light mode');
  });

  test('DOMContentLoaded wiring toggles the theme when a [data-theme-toggle] element is clicked', () => {
    const btn = document.createElement('button');
    btn.setAttribute('data-theme-toggle', '');
    document.body.appendChild(btn);

    document.dispatchEvent(new Event('DOMContentLoaded', { bubbles: true, cancelable: true }));
    btn.click();

    expect(window.Theme.current()).toBe('dark');
  });

  test('DOMContentLoaded wiring closes all open modals on Escape', () => {
    const m = document.createElement('div');
    m.id = 'my-modal';
    m.className = 'modal';
    document.body.appendChild(m);
    document.dispatchEvent(new Event('DOMContentLoaded', { bubbles: true, cancelable: true }));
    window.Modal.open('my-modal');
    expect(m.classList.contains('hidden')).toBe(false);

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));

    expect(m.classList.contains('hidden')).toBe(true);
  });
});

describe('toast', () => {
  test('creates the toast wrapper on first use and appends a message', () => {
    jest.useFakeTimers();
    window.toast('Saved!');
    const wrap = document.getElementById('toast-wrap');
    expect(wrap).not.toBeNull();
    expect(wrap.querySelector('.toast').textContent).toBe('Saved!');
    jest.useRealTimers();
  });

  test('applies a type-specific class for non-default types', () => {
    jest.useFakeTimers();
    window.toast('Oops', 'error');
    const el = document.querySelector('.toast');
    expect(el.className).toBe('toast toast-error');
    jest.useRealTimers();
  });

  test('reuses an existing wrapper on subsequent calls', () => {
    jest.useFakeTimers();
    window.toast('One');
    window.toast('Two');
    expect(document.querySelectorAll('#toast-wrap').length).toBe(1);
    expect(document.querySelectorAll('.toast').length).toBe(2);
    jest.useRealTimers();
  });

  test('removes itself from the DOM after the duration elapses', () => {
    jest.useFakeTimers();
    window.toast('Bye', 'default', 1000);
    expect(document.querySelectorAll('.toast').length).toBe(1);

    jest.advanceTimersByTime(1000);
    jest.advanceTimersByTime(220);

    expect(document.querySelectorAll('.toast').length).toBe(0);
    jest.useRealTimers();
  });
});

describe('Modal', () => {
  function makeModal(id) {
    const m = document.createElement('div');
    m.id = id;
    m.className = 'modal hidden';
    m.innerHTML = '<div class="modal-backdrop"></div><button class="modal-close">x</button>';
    document.body.appendChild(m);
    return m;
  }

  test('open() reveals the modal and locks body scroll', () => {
    const m = makeModal('m1');
    window.Modal.open('m1');
    expect(m.classList.contains('hidden')).toBe(false);
    expect(document.body.style.overflow).toBe('hidden');
  });

  test('open() on a missing id is a no-op', () => {
    expect(() => window.Modal.open('does-not-exist')).not.toThrow();
  });

  test('close() hides the modal and restores scroll', () => {
    const m = makeModal('m2');
    window.Modal.open('m2');
    window.Modal.close('m2');
    expect(m.classList.contains('hidden')).toBe(true);
    expect(document.body.style.overflow).toBe('');
  });

  test('close() on a missing id is a no-op', () => {
    expect(() => window.Modal.close('nope')).not.toThrow();
  });

  test('clicking the backdrop closes the modal', () => {
    const m = makeModal('m3');
    window.Modal.open('m3');
    m.querySelector('.modal-backdrop').dispatchEvent(new Event('click', { bubbles: true }));
    expect(m.classList.contains('hidden')).toBe(true);
  });

  test('clicking the close button closes the modal', () => {
    const m = makeModal('m4');
    window.Modal.open('m4');
    m.querySelector('.modal-close').dispatchEvent(new Event('click', { bubbles: true }));
    expect(m.classList.contains('hidden')).toBe(true);
  });

  test('closeAll() hides every open modal', () => {
    const a = makeModal('ma');
    const b = makeModal('mb');
    window.Modal.open('ma');
    window.Modal.open('mb');

    window.Modal.closeAll();

    expect(a.classList.contains('hidden')).toBe(true);
    expect(b.classList.contains('hidden')).toBe(true);
    expect(document.body.style.overflow).toBe('');
  });
});

describe('showConfirm', () => {
  test('builds the dialog once, shows the message/title, and resolves true on confirm', async () => {
    const p = window.showConfirm('Are you sure?', 'Fshi');
    expect(document.getElementById('confirm-title').textContent).toBe('Fshi');
    expect(document.getElementById('confirm-msg').textContent).toBe('Are you sure?');

    document.getElementById('confirm-yes').click();
    expect(await p).toBe(true);
  });

  test('resolves false when the "no" button is clicked', async () => {
    const p = window.showConfirm('Delete this?');
    document.getElementById('confirm-no').click();
    expect(await p).toBe(false);
  });

  test('reuses the same DOM nodes across repeated calls', async () => {
    const p1 = window.showConfirm('First');
    document.getElementById('confirm-yes').click();
    await p1;

    window.showConfirm('Second');
    expect(document.querySelectorAll('#confirm-modal').length).toBe(1);
  });
});

describe('esc / escHtml', () => {
  test('escapes the five HTML-sensitive characters', () => {
    expect(window.esc(`<b>"Tom" & 'Jerry'</b>`)).toBe(
      '&lt;b&gt;&quot;Tom&quot; &amp; &#39;Jerry&#39;&lt;/b&gt;'
    );
  });

  test('returns an empty string for null/undefined, and stringifies numbers', () => {
    expect(window.esc(null)).toBe('');
    expect(window.esc(undefined)).toBe('');
    expect(window.esc(42)).toBe('42');
  });

  test('escHtml is the same function as esc', () => {
    expect(window.escHtml).toBe(window.esc);
  });
});

describe('parseJWT', () => {
  test('decodes a valid payload', () => {
    const payload = { sub: 'abc' };
    const b64 = Buffer.from(JSON.stringify(payload)).toString('base64').replace(/\+/g, '-').replace(/\//g, '_');
    expect(window.parseJWT(`h.${b64}.s`)).toEqual(payload);
  });

  test('returns null on garbage input', () => {
    expect(window.parseJWT('garbage')).toBeNull();
  });
});

describe('fmtDate / fmtDateTime', () => {
  test('returns an em dash for empty input', () => {
    expect(window.fmtDate('')).toBe('—');
    expect(window.fmtDate(null)).toBe('—');
  });

  test('returns the raw string for an unparseable date', () => {
    expect(window.fmtDate('not-a-date')).toBe('not-a-date');
  });

  test('formats a valid date string', () => {
    const out = window.fmtDate('2026-03-15');
    expect(typeof out).toBe('string');
    expect(out).not.toBe('—');
    expect(out.length).toBeGreaterThan(0);
  });

  test('fmtDateTime includes time-of-day formatting and does not throw', () => {
    const out = window.fmtDateTime('2026-03-15T14:30:00Z');
    expect(typeof out).toBe('string');
    expect(out).not.toBe('—');
  });
});

describe('fmtALL / fmtEUR', () => {
  test('fmtALL formats a number with the Lek suffix', () => {
    expect(window.fmtALL(1500)).toMatch(/L$/);
  });

  test('fmtALL returns an em dash for non-numeric input', () => {
    expect(window.fmtALL('abc')).toBe('—');
  });

  test('fmtEUR formats with two decimals and a euro sign', () => {
    expect(window.fmtEUR(9.5)).toBe('€9.50');
  });

  test('fmtEUR returns an em dash for non-numeric input', () => {
    expect(window.fmtEUR('abc')).toBe('—');
  });
});

describe('showFeedback / hideFeedback', () => {
  test('showFeedback sets text, a type class, and reveals the element', () => {
    const el = document.createElement('div');
    el.id = 'fb';
    el.className = 'feedback hidden';
    document.body.appendChild(el);

    window.showFeedback('fb', 'Something went wrong', 'error');

    expect(el.textContent).toBe('Something went wrong');
    expect(el.className).toBe('feedback feedback-error');
    expect(el.classList.contains('hidden')).toBe(false);
  });

  test('showFeedback on a missing id is a no-op', () => {
    expect(() => window.showFeedback('missing', 'x')).not.toThrow();
  });

  test('hideFeedback re-hides the element', () => {
    const el = document.createElement('div');
    el.id = 'fb2';
    document.body.appendChild(el);
    window.showFeedback('fb2', 'msg');
    window.hideFeedback('fb2');
    expect(el.classList.contains('hidden')).toBe(true);
  });

  test('hideFeedback on a missing id is a no-op', () => {
    expect(() => window.hideFeedback('missing')).not.toThrow();
  });
});

describe('debounce', () => {
  test('only calls the wrapped function once after the delay, with the latest args', () => {
    jest.useFakeTimers();
    const fn = jest.fn();
    const debounced = window.debounce(fn, 300);

    debounced('a');
    debounced('b');
    debounced('c');
    expect(fn).not.toHaveBeenCalled();

    jest.advanceTimersByTime(300);

    expect(fn).toHaveBeenCalledTimes(1);
    expect(fn).toHaveBeenCalledWith('c');
    jest.useRealTimers();
  });

  test('uses the default 280ms delay when none is given', () => {
    jest.useFakeTimers();
    const fn = jest.fn();
    const debounced = window.debounce(fn);
    debounced();
    jest.advanceTimersByTime(279);
    expect(fn).not.toHaveBeenCalled();
    jest.advanceTimersByTime(1);
    expect(fn).toHaveBeenCalledTimes(1);
    jest.useRealTimers();
  });
});
