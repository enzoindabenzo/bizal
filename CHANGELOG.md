# BizAL — Changelog

Consolidated fix/audit history. Older `FIXES.md`, `CHANGES.md`,
`AUDIT_FIXES_v36.md`, `FINAL_AUDIT.md`, `FINAL_AUDIT_v65.md`, and
`FINAL_REPOSITORY_AUDIT.md` have been merged into this single file — each
version's own audit round is one dated section below, newest first.

---

## v90 — Seed: Retail + Hotel Tenants

- Added **`market-express`** (Shkodër, `market` business type, Starter plan)
  — the first retail-category tenant in `seed.py`. 3 product categories, 8
  products deliberately spanning normal stock, at-threshold low stock
  (custom per-product `low_stock_threshold`), and zero stock, so the
  inventory storefront states (in-stock/low-stock/out-of-stock) can finally
  be tried end-to-end instead of only through `ProductOrderTests`.
- Added **`hotel-riviera`** (Sarandë, `hotel` business type, Enterprise
  plan) for room testing — 3 `RoomType`s (Single/Double/Suite), 6 `Room`s
  spanning `available`/`occupied`/`maintenance` statuses, 2 `SeasonalPrice`
  entries (summer season), plus breakfast/airport-transfer `Service`s. Also
  Enterprise-plan, so it can exercise the chatbot alongside `hertz-albania`
  and `amos-realestate`.
- Both tenants also get an owner user, hero slide, and review set, matching
  the existing 8-tenant pattern.
- Verified by actually running `seed.py` against a fresh local SQLite DB
  (not just read through): ran twice back-to-back to confirm
  `update_or_create`/`get_or_create` idempotency, then queried the DB
  directly to confirm 8 products / 3 room types / 6 rooms / 2 seasonal
  prices landed with the intended stock/status spread.
- Full backend suite still 461/461 after the change (seed.py itself isn't
  covered by the test suite, but the new imports/models it touches are).

## v89 — Chatbot Frontend Auth-Retry Tests

- Added a Jest test harness for the frontend (`frontend/package.json`,
  `frontend/jest.config.js`, `jest-environment-jsdom`) — the repo had no JS
  test runner before this. `npm test` from `frontend/` runs it.
- `chatbot.js` only exposes `window.BizBot.init()`, so
  `static/js/__tests__/chatbot.auth.test.js` drives the real widget: it
  inits the widget in jsdom against stubbed `Auth`/`fetch` globals, types
  into the real textarea, clicks the real send button, and asserts on the
  real `fetch` calls + rendered DOM. 9 tests, covering:
  - anonymous visitor gated with zero network calls, on both the main
    domain and a tenant storefront;
  - authenticated visitor's Bearer token attached and reply rendered, on
    both the main domain and a tenant storefront (`tenant_slug` present in
    the request body only for the tenant case);
  - missing in-memory access token triggers `ensureFreshToken()`'s silent
    refresh before the first request;
  - a 401 mid-conversation triggers exactly one silent refresh + retry,
    then succeeds;
  - a 401 with a failing refresh, or with no refresh token at all, locks
    the widget in place and — critically — never touches
    `window.location.href`, confirming the deliberate choice not to route
    through `Auth.apiFetch()`'s navigate-on-failure behavior.
- Verified the suite actually catches regressions: temporarily disabled the
  retry guard in `chatbot.js`, confirmed 2 of the 9 tests failed with the
  expected assertion diffs, then restored the real file and confirmed green
  again.

## v88 — Chatbot Auth Gate Tests

- Added `chatbot/tests.py` (18 tests, new file — the app had none before):
  covers `chat()`, `handoff()`, `poll()`, and `staff_reply()` all rejecting
  anonymous callers with 401, all accepting a valid authenticated user, and
  all rejecting an expired or malformed JWT the same as a missing one.
- Every case that matters is checked on **both** the main domain and a
  tenant subdomain (`HTTP_HOST` set to `<slug>.bizal.al`), including a
  non-Enterprise (trial-plan) tenant, confirming the auth check runs before
  any plan/tenant-lookup logic.
- `chat()` tests mock `_rotate_call` so no real Groq/OpenRouter network call
  is made; `handoff()`/`poll()` tests use real HMAC-signed session tokens
  via the module's own `_make_session_token()` helper.
- Full suite: 461/461 passing.

## v81 — Homepage Page Builder

- **New:** `storefront.StorefrontSection` model + API — a drag-and-drop
  homepage builder sitting alongside Hero Slides and Extra Pages in Vitrina.
  Seven block types (text, image, CTA, gallery, features, testimonial,
  spacer), each reorderable, each independently activatable.
- Hex-color and JSON-shape validation on section fields (mirrors the
  existing `validate_hex_color` / image-upload patterns from `HeroSlide`).
- Public storefront (`index.html`) renders active sections in order between
  the hero carousel and the extra-pages cards.
- 12 new tests (`StorefrontSectionTest`); full storefront suite: 29/29.

## v68 — Final Repository Audit (fresh independent review)

Full re-review of all 300 Python files, settings, Docker/nginx config, and
docs, without trusting prior `# FIX:` comments. One low-priority finding
(`requirements.txt` pins direct dependencies only, no transitive lockfile);
everything else verified clean. No regressions found.

## v65 — Final Repository Audit

Full-repo line-by-line audit (22 apps, frontend, Docker, nginx, migrations).
Score 9.4/10 → 10.0/10 post-fix. Notable fixes:
- `docker-compose.prod.yml` `spa` service had a dead/broken inline Python
  script (Sentry alert code) that was a syntax error.
- `superadmin_trial_summary` 500'd on a non-integer `?page_size=`.
- `chatbot` rate-limiter `cache.incr()` race could leave a counter with no
  TTL, and its `page_size` clamp allowed values above the global max.
- `entrypoint.sh` had no fallback guard for an empty `$@`.

## v43 — Audit Follow-Up (v42 final audit findings)

- `CORS_ALLOW_CREDENTIALS` was only set in `dev.py`/`local.py`, never
  inherited by `production.py` — every authenticated cross-origin request
  from a tenant SPA silently failed CORS in production.
- `MeView.get_object()` and `SuperadminUserListView` were missing
  `select_related`/N+1 guards.
- Chatbot's main-domain daily counter used a non-atomic get+set race; a
  follow-up round also found the JS chat widget never adopted the
  server-issued HMAC session token, and the handoff endpoint accepted an
  empty `session_id`, bypassing HMAC verification entirely (critical).
- `send_sms_stub` unconditionally returned `SUCCESS` with no real delivery.
- nginx had no `default_server` catch-all for unrecognised hostnames.

## v36 — Audit Fix Round (16 findings from v35 audit)

- `superadmin_panel`'s JWT gate read `request.COOKIES`, but tokens are only
  ever stored in `localStorage` — the gate was always `False`, causing an
  infinite login redirect loop. Removed; the panel is API-data-only and
  DRF's `IsAdminUser` is the real enforcement point.
- `LoyaltyTransaction` was missing a uniqueness constraint; CORS regex
  dropped `http://` in production; `validate_image_type` read the image
  format *after* calling `.verify()` (which clears it); Celery result
  backend moved to its own Redis DB to avoid cache collisions.

## v32 and earlier — Bug Fixes & Improvements

Early-stage hardening pass across the whole stack:

- **Tenant isolation / middleware:** `www.` prefix stripping in
  `TenantMiddleware`; registration blocked from the main domain;
  `StaffMember` soft-deactivated (not deleted) on account removal; hotel
  room-booking overlap check; `analytics/utils.py` tenant guard.
- **Data integrity:** guarded against accidental tenant CASCADE deletes;
  `CreditLedger` balance validation; `TenantFeature.value` normalisation.
- **Security:** JWT refresh tokens invalidated on staff removal; superadmin
  actions logged; password-reset tokens expire in 1 hour.
- **API design:** versioning, pagination applied consistently,
  `StaffDetailView` soft-delete.
- **Reliability/ops:** Celery task retry logic, `CONN_HEALTH_CHECKS`,
  `CONN_MAX_AGE` tuning, structured logging, DB backup service, CI
  migration check.
- **Frontend:** tenant-admin error boundary, JWT auto-refresh before
  expiry, URL persistence on refresh, dark/light theme, per-tenant admin
  pages, superadmin panel, professional styling pass.
- **Docker/nginx:** fixed missing `events {}`/`http {}` blocks in the root
  `nginx.conf`, `Dockerfile` running `COPY`/`chmod` as non-root, missing
  `X-Forwarded-Proto` causing an infinite redirect loop in production,
  `spa` container starting without running migrations, and several
  `README.md` inaccuracies (wrong service names, invalid `ALLOWED_HOSTS`
  glob, a `STRIPE_PUBLISHABLE_KEY` that isn't in settings).
- **Correctness:** `send_booking_reminders` could re-send up to 24 emails
  per guest per day; chatbot queried a `stock_quantity` field that doesn't
  exist on `Product` (it's `stock`).

---

## Architectural milestones (not audit rounds)

These are structural changes worth knowing about when reading older code
or migrations, independent of any single audit round above:

- **Superadmin merge:** the standalone `superadmin.html` SPA was retired;
  its functionality (trial activation clock, owner notification emails,
  `is_custom_grant` flag) was ported into `/django-admin/` via Unfold's
  dashboard callback system and `TenantAdmin.save_model()`.
- **Storefront customization:** tenant-facing storefront customization,
  feature-gated nav items, drag-and-drop hero-slide/page reordering (with
  a serialized persist queue to prevent race conditions on rapid
  reorders), and — as of v81 — the full homepage section builder.
- **Rebrand:** Cormorant Garamond + DM Sans, warm neutral palette, shared
  `brand.css` / `ui.js` / `auth.js` across both the storefront and tenant
  admin SPAs.
- **CSRF/proxy fix:** `CSRF_TRUSTED_ORIGINS` configured for Django 4.2
  running behind an nginx reverse proxy.

For current architecture (tenant resolution, base model hierarchy, feature
flags, Celery, settings modules), see `ARCHITECTURE.md`. For setup, API
overview, and local dev commands, see `README.md`.
