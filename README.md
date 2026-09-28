# BizAL — Multi-Tenant SaaS Platform for Albanian SMBs

![tests](https://github.com/enzoindabenzo/bizal/actions/workflows/tests.yml/badge.svg)
![coverage](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/enzoindabenzo/bizal/main/.github/badges/coverage.json)

BizAL is a Django REST Framework backend powering white-label portals for 51 Albanian business types (restaurants, hotels, clinics, car rentals, gyms, pharmacies, retail, and more — see `BUSINESS_TYPE_CHOICES` in `tenants/models.py` for the full list). Each business gets its own branded subdomain and feature set based on their subscription plan.

1389 backend tests, ~95% coverage locally against SQLite (CI enforces ≥85%, measured against real PostgreSQL — see [Testing](#testing)).

---

## Table of Contents

- [Repository Layout](#repository-layout)
- [Architecture](#architecture)
  - [Tenant Resolution](#tenant-resolution)
  - [Base Model Hierarchy](#base-model-hierarchy)
  - [Platform vs Tenant Models](#platform-vs-tenant-models)
  - [Feature Flags & Plans](#feature-flags--plans)
  - [Middleware Caching](#middleware-caching)
  - [Celery](#celery)
  - [Settings Modules](#settings-modules)
  - [Credit Ledger](#credit-ledger)
  - [Concurrency / Row Locking](#concurrency--row-locking)
  - [Homepage Page Builder](#homepage-page-builder)
  - [JWT Storage (Frontend)](#jwt-storage-frontend)
- [Local Development (Windows)](#local-development-windows)
- [Local Development (Linux / macOS)](#local-development-linux--macos)
- [API Overview](#api-overview)
- [Docker / Production](#docker--production)
  - [Free Pilot Deployment](#free-pilot-deployment-no-domain-purchase-no-paid-hosting)
  - [Railway Deployment](#railway-deployment)
- [Testing](#testing)
- [Load Testing](#load-testing)
- [Research Artifacts](#research-artifacts-thesis)
- [Adding a New Business Type](#adding-a-new-business-type)
- [Adding a New App](#adding-a-new-app)
- [Notable Design Decisions](#notable-design-decisions)

---

## Repository Layout

```
bizal/
├── backend/                 Django project root
│   ├── bizal/                Core settings, URLs, Celery, base models
│   ├── accounts/              JWT auth, user profiles, password reset
│   ├── activity/               Cross-app activity/audit log
│   ├── tenants/                 Multi-tenancy, plans, features, middleware
│   ├── appointments/             Calendar-based booking (clinics, spas, gyms)
│   ├── analytics/                  Dashboard stats + CSV export (Enterprise)
│   ├── billing/                     Invoices + line items for tenant customers
│   ├── blog/                         Tenant blog with tags, slugs, view counts
│   ├── bookings/                       Generic booking engine (tables, rooms, cars)
│   ├── chatbot/                         AI storefront chat widget + staff handoff
│   ├── contact/                          Contact form with email + notifications
│   ├── crm/                                Lead pipeline with notes
│   ├── hotels/                              Room types, rooms, seasonal pricing
│   ├── inventory/                            Products + categories
│   ├── loadtest/                              Locust load test (see below)
│   ├── menu/                                   Restaurant menu categories/items
│   ├── notifications/                           In-app notification system
│   ├── orders/                                   Storefront cart + fulfillment
│   ├── payments/                                   Stripe checkout + webhooks
│   ├── rentals/                                     Rental catalogue + availability
│   ├── research/                                     SUS usability-survey API (thesis pilot) — a real installed
│   │                                                  Django app, NOT the same thing as the top-level research/
│   │                                                  folder below (that one holds the pilot's docs, not code)
│   ├── reviews/                                       Reviews + platform reviews
│   ├── staff/                                          Staff roster + schedules
│   ├── storefront/                                       Page builder, hero slides
│   └── subscriptions/                                      Recurring subscriptions
├── frontend/                 Static HTML/CSS/JS (multi-page SPA, no build step)
├── research/                 Thesis pilot materials (usability survey, timing methodology)
├── dev.py                    Local dev launcher (ports 8000 + 8001)
├── activate.ps1              PowerShell dev helpers (Windows)
├── docker-compose.yml        Development stack (DEBUG=True, Dockerfile.dev, runserver)
├── docker-compose.prod.yml   Production stack (Dockerfile, production settings, gunicorn)
├── Dockerfile
├── .env.example              Every env var read by settings/production.py
├── nginx.conf                 Standalone host nginx (VPS/bare-metal deployment)
└── nginx/nginx.conf           Docker nginx service config (different deployment path)
```

---

## Architecture

BizAL is a single Django backend serving two logical "zones": the **main platform** (marketing site, signup, marketplace) and **tenant spaces** (each business's own subdomain).

### Tenant Resolution

Requests are resolved to a tenant via `TenantMiddleware._resolve_tenant()`, which sets `request.tenant` on every request. It tries, in order:

1. **Subdomain** — `hertz-albania.bizal.al` → slug `hertz-albania` (production), or `hertz-albania.localhost:8001` (local dev, if you've added it to `/etc/hosts`)
2. **Local-dev query param + session** — on `localhost:8001` (`TENANT_PORT`), `?tenant=hertz-albania` sets the slug for the session; a later request with no `?tenant=` on that same port reuses the remembered slug
3. **Single-origin "bring-up" fallback** — for a platform-only deployment with no wildcard DNS yet (a bare `*.up.railway.app` domain, before a custom domain is attached), there's no subdomain to resolve a tenant from at all. When `ALLOW_TENANT_QUERY_PARAM=True` (see `.env.railway.example`), the middleware applies the same `?tenant=<slug>` + remembered-session strategy as tier 2, but on whatever host actually served the request

| Environment | Main platform | Tenant portal |
|---|---|---|
| Local dev | `localhost:8000` | `localhost:8001/?tenant=x` or `x.localhost:8001` |
| Production (custom domain) | `bizal.al` | `x.bizal.al` |
| Production (bare Railway domain, no custom domain yet) | `web-production-xxxx.up.railway.app` | same host, `?tenant=x` |

**Important gotcha in tier 3** (fixed — see `tenants/middleware.py` comments for the full history): a visitor's remembered session tenant must never leak into `/api/auth/login/` or `/api/auth/register/`. Those two paths are excluded from the session fallback (`AUTH_PATHS_EXCLUDE_SESSION_FALLBACK`) so that someone who previously clicked into a tenant demo on the same bare domain can still log into the *main site* afterwards without the login POST silently inheriting that old tenant and getting rejected with "Superadmins must use the admin panel, not a tenant portal." A page load (`GET /`) already always resolves as the main site regardless of session state — this fix makes login/register behave the same way. An explicit `?tenant=` on the login request itself still works; only the *stale remembered* value is ignored.

Resolution outcomes:
- **Main domain** (or excluded auth path in tier 3) → `request.tenant = None`
- **Tenant subdomain / resolved slug** → `request.tenant = <Tenant instance>` (active, or trial-expired with `is_active=False`)
- **Unknown slug** → `Http404`

All tenant-scoped API views filter querysets by `request.tenant` — never by `request.user.tenant` in tenant-facing views, so isolation is enforced at the middleware level, not per-view.

### Base Model Hierarchy

```
models.Model
  └── UUIDModel                    (uuid pk)
  └── TimeStampedModel             (created_at, updated_at)
  └── TenantScopedModel            (non-nullable tenant FK + timestamps)
        └── TenantScopedUUIDModel  (uuid pk + tenant FK + timestamps)  ← use this
```

Every model that belongs to a tenant should inherit from `TenantScopedUUIDModel` (in `bizal/base_models.py`). A raw `ForeignKey(Tenant, ...)` directly on a model is a code smell — it's easy to accidentally make it nullable, which allows orphaned rows and bypasses the CASCADE guarantee.

### Platform vs Tenant Models

Some apps have both a **tenant model** (data belonging to one business) and a **platform model** (data about the platform itself, visible across all tenants). The canonical example is `reviews/`:

| File | Scope |
|---|---|
| `reviews/models.py` | Per-tenant reviews (guests reviewing a business) |
| `reviews/platform_models.py` | Platform reviews (users reviewing BizAL itself) |
| `reviews/platform_views.py` | Views for platform review endpoints |
| `reviews/platform_urls.py` | URL patterns for platform review endpoints |

When an app needs platform-level resources, follow this same pattern rather than inventing a new one — keep platform files in the same app directory, don't create a separate `platform/` app.

### Feature Flags & Plans

Plan capabilities are stored in `TenantFeature` rows (key/value per tenant). `Tenant.has_feature('bookings')` is the canonical check; the `HasTenantFeature('bookings')` permission class uses it. The table below is generated from `PLAN_FEATURES` in `tenants/models.py` — treat that dict as the source of truth if this ever drifts again.

| Feature | Free (Starter) | Pro | Enterprise |
|---|---|---|---|
| Menu/Services | ✓ | ✓ | ✓ |
| Bookings | ✓ | ✓ | ✓ |
| Reviews | ✓ | ✓ | ✓ |
| Blog | | ✓ | ✓ |
| Notifications (SMS) | | ✓ | ✓ |
| Staff Management | | ✓ | ✓ |
| Inventory | | ✓ | ✓ |
| Referral Program | | ✓ | ✓ |
| Custom Pages / Homepage Builder (`custom_branding`) | | ✓ | ✓ |
| Analytics Dashboard | | ✓ | ✓ |
| CRM / Leads | | | ✓ |
| Invoicing | | | ✓ |
| PDF Export | | | ✓ |
| CSV Export | | | ✓ |
| API Access | | | ✓ |
| Multi-Location | | | ✓ |
| Loyalty Program | | | ✓ |
| Custom Domain | | | ✓ |
| Chatbot | | | ✓ |

**Business-type overrides.** `BUSINESS_TYPE_PRESETS` (also in `tenants/models.py`) layers on top of the plan defaults above and can grant a feature *regardless of the tenant's plan* — e.g. every `hotel` and `clinic` tenant gets `crm: True` even on Free/Pro, and a `real_estate`, `lawyer`, or `accounting` tenant gets `invoicing` + `pdf_export` on any plan. Booking-heavy types (`restaurant`, `hotel`, `clinic`, `barbershop`, `gym`, etc.) are always given `bookings: True` even though it's already a base-plan feature. Only the keys listed for a given business type are overridden — everything else still falls back to the plan default in the table above. `apply_plan_defaults()` runs from `Tenant.save()` whenever plan or business type changes, using `bulk_create(..., update_conflicts=True)` — a single DB round-trip instead of an N×`update_or_create` loop. Custom grants (`is_custom_grant=True`), set by superadmins, are never overwritten by plan or business-type changes.

### Middleware Caching

`TenantMiddleware._get_tenant()` caches the resolved `Tenant` object in Redis for 5 minutes, populated via `prefetch_related('features', 'locations')` before storage — so `tenant.has_feature()` iterates an in-memory list rather than hitting the DB. On cache hit, `has_feature()`'s `self.features.all()` call returns the cached list rather than issuing a new query.

### Celery

- **Worker**: `celery -A bizal worker`
- **Beat**: `celery -A bizal beat --scheduler django_celery_beat.schedulers:DatabaseScheduler`
- Periodic tasks are defined in `settings/base.py` under `CELERY_BEAT_SCHEDULE`.
- The DB-backed scheduler (`django_celery_beat`) persists last-run timestamps across container restarts — without it, all periodic tasks would re-run immediately on every beat container restart.

### Settings Modules

| Module | Used when |
|---|---|
| `settings/base.py` | Shared config inherited by all |
| `settings/local.py` | Local dev, running directly on the host (`manage.py` / `activate.ps1` / `install.sh`) — SQLite, no Redis, Celery in eager mode |
| `settings/dev.py` | Dockerized dev stack (`docker-compose.yml`) — real Postgres, real Redis, real (non-eager) Celery, close to production but with relaxed security for plain-HTTP localhost |
| `settings/test.py` | pytest / CI (SQLite locally; real Postgres in CI — see [Testing](#testing)) |
| `settings/production.py` | Docker Compose production stack **and** Railway — HTTPS headers, structured logging, trusts `X-Forwarded-Proto` |

Don't confuse `settings/local.py` with `settings/dev.py` — they look similar but target different stacks (bare host vs. Docker); running `settings/dev.py` directly on the host fails immediately since it expects `collectstatic` to have already produced a static manifest.

`DJANGO_SETTINGS_MODULE` is set in `docker-compose.yml` (`bizal.settings.dev`), `docker-compose.prod.yml` and `.env.railway.example` (`bizal.settings.production`), and `dev.py` / `activate.ps1` (`bizal.settings.local`, local host); it should also be set in `.env` as a safety net.

### Credit Ledger

`Tenant.referral_credits` is the running balance for fast reads. Every change to that balance is mirrored as an append-only `CreditLedger` row (`tenants/models.py`) for audit trail and display. Write credits via `TenantReferral.apply_credit()` only — never mutate `referral_credits` directly.

### Concurrency / Row Locking

Anywhere a `select_for_update()` needs a bound on how long a concurrent caller can block on the row lock (invoice line creation, credit spending, seat/room booking, tenant plan limit checks, etc.), the call site uses `bizal.db_utils.set_lock_timeout(cursor)` rather than raw SQL. It wraps a single call:

```python
with transaction.atomic():
    with connection.cursor() as cursor:
        set_lock_timeout(cursor)   # SET LOCAL lock_timeout = '3s' — Postgres only
    locked = SomeModel.objects.select_for_update().get(pk=pk)
```

`SET LOCAL` is PostgreSQL-only syntax; SQLite has no equivalent and raises a syntax error if it's ever sent one directly. `set_lock_timeout()` checks `cursor.db.vendor` and no-ops on SQLite (whose single-writer locking makes the timeout meaningless there anyway), so the exact same code path runs unmodified in local dev (`settings/local.py`, SQLite), the Docker dev stack (`settings/dev.py`, Postgres), tests (`settings/test.py`, SQLite locally / Postgres in CI), and production (`settings/production.py`, Postgres) — instead of every call site needing its own `if connection.vendor == 'postgresql'` guard, or silently breaking on SQLite the way each of these previously did:

`billing/models.py`, `tenants/models.py`, `tenants/limits.py`, `staff/views.py`, `orders/views.py`, `payments/views.py`, `bookings/views.py`, `hotels/views.py`, `inventory/views.py`, `appointments/views.py`.

If you add a new `select_for_update()` call site that needs this guard, import `set_lock_timeout` from `bizal.db_utils` rather than writing the raw `cursor.execute("SET LOCAL ...")` again.

### Homepage Page Builder

The tenant homepage is built from an ordered list of `StorefrontSection` rows, each with a `section_type` (text, image, cta, gallery, features, testimonial, spacer). Shared fields (`title`, `subtitle`, `body`, `image`, `cta_label`, `cta_url`, `background_color`) cover most block types directly; anything needing a variable-length list (gallery images, feature items) goes in the `data` JSONField instead of a separate table per type. Adding a new block type is a matter of extending `SECTION_TYPE_LABELS` / `sectionTypeFields()` on the frontend and a `data`-shape check in `StorefrontSectionSerializer.validate_data()` on the backend — no new model or migration needed unless a type needs a field that doesn't fit the shared shape.

Reordering (sections, hero slides, extra pages) all share one frontend pattern: `initReorder()` in `tenant_admin.html` wires up drag handles and ▲▼ buttons on a `<tbody>`, then persists via serialized PATCH `order` writes (deliberately serialized rather than fired concurrently — see the comment above `initReorder`). Any new reorderable list should reuse `initReorder()` rather than reimplementing drag-and-drop.

### JWT Storage (Frontend)

Access and refresh tokens are stored in `localStorage` in the tenant SPA (`index.html`) — a deliberate tradeoff; see the `Auth` object comment in `index.html` for the reasoning and when it should be revisited.

---

## Local Development (Windows)

### First-time setup

```powershell
python setup.py          # creates venv, installs deps, migrates, seeds
. .\activate.ps1         # load dev commands into shell
```

### Daily workflow

```powershell
bizal-start              # starts both servers (port 8000 + 8001)
bizal-migrate            # makemigrations + migrate
bizal-seed                # re-seed demo data
bizal-test                 # run all tests
bizal-coverage               # tests + coverage report
bizal-shell                    # Django interactive shell
bizal-help                       # show all commands
```

## Local Development (Linux / macOS)

```bash
bash install.sh          # venv, deps, migrate, seed, verifies feature flags applied
python manage.py runserver 8000    # main domain, in one terminal
python manage.py runserver 8001    # tenant portals, in another
celery -A bizal worker -l info     # task queue (optional for most local work)
celery -A bizal beat -l info       # scheduled tasks (optional)
```

There's no `activate.ps1`-equivalent shortcut file for bash yet — the `bizal-*` commands are Windows-only for now; on Linux/macOS just call `python manage.py <command>` directly from `backend/`.

### Demo URLs

| URL | Description |
|---|---|
| `http://localhost:8000` | Landing page |
| `http://localhost:8000/admin` | Django admin (`admin@bizal.al` / password printed by `seed.py`, or set `SEED_ADMIN_PASSWORD` in `.env` first) |
| `http://localhost:8001/?tenant=restorant-adriatiku` | Restaurant (Pro) |
| `http://localhost:8001/?tenant=hertz-albania` | Car Rental (Enterprise) |
| `http://localhost:8001/?tenant=klinika-shendeti` | Clinic (Pro) |
| `http://localhost:8001/?tenant=hotel-riviera` | Hotel (Enterprise) |
| `http://localhost:8001/?tenant=market-express` | Retail (Starter) |

---

## API Overview

Base URL: `/api/`

| App | Path | Access |
|---|---|---|
| Auth | `/api/auth/` | `register/`, `login/`, `token/refresh/`, `password-reset/` public · `logout/`, `me/`, `change-password/` authenticated |
| Tenants | `/api/tenants/` | `info/` public · `signup/` public · `me/` owner |
| Menu | `/api/menu/` | Public read · owner manages categories/items |
| Bookings | `/api/bookings/` | Public create · owner lists/manages |
| Reviews | `/api/reviews/` | Authenticated create · public approved list · owner approves |
| Blog | `/api/blog/` | Public read by slug/tag · owner manages posts |
| Notifications | `/api/notifications/` | `GET /`, `GET /unread-count/`, `POST /mark-all-read/`, `POST /<pk>/read/` |
| Analytics | `/api/analytics/` | Owner only · `?start_date=&end_date=` · `?export=csv` (Enterprise) |
| Storefront | `/api/storefront/` | `pages/`, `hero/`, `sections/` public · `manage/*` owner |
| CRM | `/api/crm/` | Staff+ · `leads/`, `leads/<pk>/notes/` |
| Billing | `/api/billing/` | Staff+ · `invoices/`, `invoices/<pk>/lines/` |
| Research | `/api/research/` | `sus/config/` public · `sus/` owner/manager submit — SUS usability-survey (thesis pilot) |
| Subscriptions | `/api/subscriptions/` | Staff+ list · owner manage · `mine/` customer |
| Staff | `/api/staff/` | Staff read · owner manage |
| Inventory | `/api/inventory/` | `categories/` + list/detail/manage |
| Hotels | `/api/hotels/` | `room-types/`, `room-types/<pk>/seasonal-prices/`, `rooms/` |
| Rentals, Appointments, Payments, Contact | — | Standard CRUD — see individual app `urls.py` |

---

## Docker / Production

Use `docker-compose.prod.yml` for production deployments. `docker-compose.yml` is the **development** stack — hardcodes `DEBUG=True`, `Dockerfile.dev`, Django's `runserver`. `docker-compose.prod.yml` builds from the root `Dockerfile`, uses `bizal.settings.production` (gunicorn, all safety guards active), and correctly mounts the media volume into nginx.

```bash
cp .env.example .env                                      # fill in secrets
docker compose -f docker-compose.prod.yml up -d --build    # production
# — or for local development:
docker compose up -d                                      # dev stack
```

See `.env.example` for the full, current list of environment variables (kept in sync with `backend/bizal/settings/production.py` — includes DB, Redis, Stripe, email, and the six AI chatbot API keys).

**Expected `manage.py check` warning:** `manage.py check` (and `manage.py check --deploy`, and whatever startup check the container runs) will always report one warning:

```
WARNINGS:
accounts.User: (auth.W004) 'User.email' is named as the 'USERNAME_FIELD', but it is not unique.
```

This is expected, not a bug — `email` is deliberately **not** globally unique (see the `NOTE:` comment on `accounts/models.py`'s `User.email` field). BizAL is multi-tenant: the same person can hold a separate account on more than one tenant's portal (e.g. a customer of two different restaurants), so uniqueness is enforced *per-tenant* via a `UniqueConstraint(fields=['email', 'tenant'])` instead of a global one. Django's `auth.W004` check has no way to express "unique per some other field," so it always flags this regardless. Safe to ignore in every environment — don't spend time chasing it, and don't add `unique=True` back to `email` (that was the actual bug it exists to avoid; see the model comment for what broke before).

### Railway Deployment

Railway is a supported production target alongside `docker-compose.prod.yml` — it builds straight from the repo's root `Dockerfile` (see `railway.toml`), not from either docker-compose file.

1. Create a `web` service pointed at this repo. `railway.toml` sets the Dockerfile build, the `/health/` healthcheck, and a restart policy — no further Railway config needed for it.
2. Add Postgres and Redis (Railway's own plugins, or external ones) and copy the variables from **`.env.railway.example`** into the service's variables — it's kept in sync with what `bizal.settings.production` actually reads, including `DJANGO_SETTINGS_MODULE=bizal.settings.production`.
3. Create `celery-worker` and `celery-beat` services from the **same** repo/Dockerfile, but override their Start Command in the Railway dashboard (Railway can't express three different start commands from one `railway.toml`) — see the comment at the top of `railway.toml` for the exact commands.
4. On every deploy, `entrypoint.sh` runs `migrate`, syncs the Celery beat schedule, and runs `collectstatic` — **it does not seed any data or create an admin account.** There's no automatic superadmin bootstrap step at all; see the next point.
5. **Creating/resetting the admin account**: use Railway's dashboard shell (or `railway ssh` from the CLI — not `railway run`/`railway shell`, which execute *locally* with Railway's env vars injected rather than inside the real deployed container) to run, against the real production DB:
   ```bash
   python manage.py createsuperuser          # if admin@bizal.al doesn't exist yet
   python manage.py changepassword admin@bizal.al   # if it exists but the password is lost
   ```
   `seed.py` also works there (it creates the same superadmin plus a full set of demo tenants) if you want Railway to carry the same demo data as local dev — but for a real deployment, `createsuperuser`/`changepassword` alone is usually what you want.
6. **No wildcard DNS yet?** Until a custom domain with wildcard DNS is attached, set `ALLOW_TENANT_QUERY_PARAM=true` so tenants are still reachable via `?tenant=<slug>` on the bare `*.up.railway.app` domain — see [Tenant Resolution](#tenant-resolution) for exactly how that fallback behaves (and the login/register gotcha it used to have).

### Free pilot deployment (no domain purchase, no paid hosting)

For a small pilot (a handful of real users trying it, not production traffic), the whole stack can run for **€0**:

1. **Compute**: a free-tier VM with enough RAM for the full `docker-compose.prod.yml` stack (Django + Postgres + Redis + nginx) — e.g. Oracle Cloud's Always Free Ampere tier (4 OCPU / 24GB RAM, free forever) or Google Cloud's free `e2-micro`.
2. **Domain**: no purchase needed. A free wildcard-DNS service like [sslip.io](https://sslip.io) or [nip.io](https://nip.io) resolves `anything.<your-server-ip>.sslip.io` straight to your server's IP with zero DNS setup — e.g. `hertz.203-0-113-5.sslip.io`.
3. **Config**: set `MAIN_DOMAIN=203-0-113-5.sslip.io` (and matching `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `FRONTEND_BASE_URL`) in `.env`. `MAIN_DOMAIN` used to be hardcoded to `'bizal.al'` directly in `tenants/middleware.py` — it's now read from settings (see [Tenant Resolution](#tenant-resolution)) specifically so this works.
4. **Error/performance monitoring**: [Sentry](https://sentry.io) has a free tier; `SENTRY_DSN` is already wired into `settings/production.py` — just paste the DSN into `.env`, no code changes needed.
5. **Usage/onboarding monitoring**: every tenant that finishes the onboarding wizard automatically logs an `ActivityLog(verb='onboarding.completed')` entry with real elapsed time — see `research/onboarding_timing_methodology.md`. No manual stopwatch needed once this is deployed; check via Django admin (`/django-admin/`) → Activity Log, filtered by verb.

Tell pilot users a fake/throwaway signup email is fine functionally (nothing gates on `is_email_verified` — it's informational only) — the only thing that breaks with a fake email is *their own* password-reset link and any booking-confirmation emails a customer of theirs might expect, neither of which affects the pilot itself.

---

## Testing

```bash
cd backend
python manage.py test                        # all tests
python manage.py test accounts tenants crm   # specific apps
coverage run manage.py test && coverage report --fail-under=85
```

Locally this runs against SQLite (in-memory, no external services required) and currently measures **~95% coverage**. **CI** (`.github/workflows/tests.yml`) additionally runs the full suite via `pytest`/`coverage` against real **PostgreSQL 16**, specifically to exercise Postgres-only behaviour that SQLite would silently skip: `select_for_update()` locking (including the `SET LOCAL lock_timeout` guard in [Concurrency / Row Locking](#concurrency--row-locking), which no-ops on SQLite), `NULLS LAST` ordering, `JSONField` queries, `CheckConstraint` enforcement. CI enforces `coverage report --fail-under=85` — the CI run (against Postgres) is the authoritative coverage number, always somewhat higher than the local SQLite figure above precisely because of those Postgres-only branches; check the latest `backend-coverage` artifact on GitHub Actions rather than trusting either number in this README for long.

1389 tests total, all passing, spread across:

| App | Tests | App | Tests |
|---|---|---|---|
| `tenants` | 287 | `accounts` | 120 |
| `payments` | 119 | `chatbot` | 104 |
| `bookings` | 74 | `hotels` | 69 |
| `bizal` (dashboard, validators, celery sync, tenant isolation) | 60 | `billing` | 59 |
| `notifications` | 52 | `orders` | 51 |
| `appointments` | 47 | `reviews` | 46 |
| `storefront` | 40 | `analytics` | 39 |
| `inventory` | 35 | `staff` | 31 |
| `rentals` | 30 | `contact` | 24 |
| `research` | 21 | `crm` | 19 |
| `activity` | 16 | `blog` | 16 |
| `menu` | 15 | `subscriptions` | 15 |

Isolation checks (a tenant can never read/write another tenant's data) aren't confined to one file — they're woven into nearly every app's test suite, plus a dedicated `bizal/tests/test_tenant_isolation.py`. There's also a separate **static** regression gate (`backend/bizal/tests/check_tenant_isolation.py`, no DB/Django needed — pure `ast`) that scans every DRF view and fails CI if a *new* view is added without a tenant-aware permission class; see `backend/bizal/tests/TENANT_ISOLATION_CHECK_README.md`.

Frontend has a separate Jest harness (`frontend/`, `npm test`) — 121 tests covering auth/token-refresh, the chatbot widget, and general UI helpers against a real DOM (jsdom).

---

## Load Testing

`backend/loadtest/` (Locust) answers the performance question that unit tests can't: how does the platform behave under concurrent multi-tenant traffic? See `backend/loadtest/README.md` for full instructions and methodology.

Quick start:

```bash
cd backend
python manage.py runserver 0.0.0.0:8000     # terminal 1
make loadtest                                # terminal 2 (repo root), defaults: 50 users, 60s
```

`backend/loadtest/results/` is gitignored (see `.gitignore`) — none of the CSVs below exist on GitHub, only on whatever machine actually ran the test. The numbers here are transcribed from a local run so they're not lost entirely, but the raw files themselves aren't retrievable from the repo; re-run the commands above if you need the underlying data.

Floor baseline (dev server, single-threaded `runserver`, SQLite — worst case, not production), 30 concurrent users: **382 requests, 0% failures, 9ms median / 44ms p95** response time across all endpoint types and tenants. `backend/loadtest/README.md` has the full per-endpoint breakdown, but note its claim that this is "committed" at `results/baseline_devserver_20260731_stats.csv` is itself stale for the same reason — that path is gitignored too, so the file isn't actually on GitHub either.

Beyond that floor baseline, local runs at higher concurrency (200/500/1000 users, production-mode via `docker-compose.prod.yml` + gunicorn) exist only as local artifacts, never committed and never written up before now:

| Concurrent users | Requests | Failures | Median | Max |
|---|---|---|---|---|
| 200 | 6,955 | 0 (0%) | 110ms | 1.5s |
| 500 | 7,113 | 31 (0.4%) | 3.8s | 30s |
| 1000 | 11,616 | 1,152 (9.9%) | 9.1s | 54s |

Clean up to ~200 concurrent users, visible degradation by 500, and a real failure rate by 1000 — consistent with the gunicorn worker/thread-count tuning notes in `entrypoint.sh` (re-derive `GUNICORN_WORKERS`/`GUNICORN_WEB_THREADS` from the actual deployment's core count rather than trusting a number carried over from a different machine). None of this is related to the SQLite-only `SET LOCAL` issue described in [Concurrency / Row Locking](#concurrency--row-locking) — these runs already used real Postgres, where that statement always worked correctly; the degradation here is capacity/tuning, not the bug that was fixed.

If these numbers are worth keeping around, either remove `results/` from `.gitignore` for specific named baseline files (not the whole directory — `make loadtest`'s timestamped runs would otherwise flood the repo with one CSV set per run) or copy the numbers into a written summary the way this table does.

---

## Research Artifacts (Thesis)

`research/` holds materials for the thesis pilot/evaluation arm — not part of the running application:

- **`usability_survey_sus.md`** — a standard System Usability Scale (SUS) questionnaire (Albanian), plus pilot protocol (who to recruit, how many, how to score).
- **`onboarding_timing_methodology.md`** — a repeatable protocol for measuring tenant onboarding time (who times it, start/end points, what to record), so results are more than one developer's single manual run.

---

## Adding a New Business Type

1. Add the slug + label to `BUSINESS_TYPE_CHOICES` in `tenants/models.py`
2. Run `bizal-migrate`
3. Add a seed entry in `seed.py` if wanted
4. Any app-specific feature (e.g. `has_feature('table_reservations')`) goes in `TenantFeature` and gets seeded by `apply_plan_defaults()`

## Adding a New App

```bash
cd backend
python manage.py startapp myapp
```

Then:
- Inherit models from `TenantScopedUUIDModel` in `bizal/base_models.py`
- Add `'myapp'` to `LOCAL_APPS` in `settings/base.py` (this feeds into `INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS` — don't edit `INSTALLED_APPS` directly)
- Add `path('api/myapp/', include('myapp.urls'))` in `bizal/urls.py`
- Run `bizal-migrate`

Pick a name that doesn't collide with a top-level repo directory — `research/` is both a `LOCAL_APPS` entry (`backend/research/`, the SUS survey API) and an unrelated top-level docs folder (thesis materials); see the note in [Repository Layout](#repository-layout). A fresh app name shouldn't repeat that mistake.

---

## Notable Design Decisions

- The standalone `superadmin.html` SPA was retired in favor of `/django-admin/` via Unfold's dashboard callbacks.
- Tenant storefront customization is a full drag-and-drop homepage section builder — see [Homepage Page Builder](#homepage-page-builder).
- Shared typography (Cormorant Garamond + DM Sans) and a warm neutral palette are defined once in `brand.css` / `ui.js` / `auth.js` and reused across storefront and tenant admin.
- `CSRF_TRUSTED_ORIGINS` is read from an env var (default `https://bizal.al,https://*.bizal.al`) rather than relying on Django's same-origin check alone — needed because any proxy hop that loses the original scheme (nginx in `docker-compose.prod.yml`, or Railway's edge, which has no nginx at all) can otherwise make same-origin CSRF checks fail on `/django-admin/` and other Django-rendered POST forms.
- Chatbot endpoints are covered by a dedicated auth-gate test suite (every endpoint rejects anonymous/expired/malformed JWTs on both main domain and tenant subdomains) plus a frontend Jest harness driving the real chat widget in jsdom.
- `select_for_update()` row-locking guards (`bizal.db_utils.set_lock_timeout`) work unmodified across SQLite and Postgres — see [Concurrency / Row Locking](#concurrency--row-locking) for why a naive `cursor.execute("SET LOCAL ...")` at each call site broke local dev and `seed.py` entirely.
- On a single-origin deployment with no wildcard DNS (bare Railway domain), `/api/auth/login/` and `/api/auth/register/` deliberately ignore a remembered session tenant that other `/api/...` calls are allowed to fall back to — see [Tenant Resolution](#tenant-resolution) for why, and what broke before this exclusion existed.