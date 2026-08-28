# BizAL — Multi-Tenant SaaS Platform for Albanian SMBs

![tests](https://github.com/enzoindabenzo/bizal/actions/workflows/tests.yml/badge.svg)
![coverage](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/enzoindabenzo/bizal/main/.github/badges/coverage.json)

BizAL is a Django REST Framework backend powering white-label portals for 26 Albanian business types (restaurants, hotels, clinics, car rentals, gyms, pharmacies, retail, and more). Each business gets its own branded subdomain and feature set based on their subscription plan.

1332 backend tests, 100% coverage (85% enforced in CI), tested against real PostgreSQL — see [Testing](#testing).

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
  - [Homepage Page Builder](#homepage-page-builder)
  - [JWT Storage (Frontend)](#jwt-storage-frontend)
- [Local Development (Windows)](#local-development-windows)
- [Local Development (Linux / macOS)](#local-development-linux--macos)
- [API Overview](#api-overview)
- [Docker / Production](#docker--production)
  - [Free Pilot Deployment](#free-pilot-deployment-no-domain-purchase-no-paid-hosting)
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

Requests are resolved to a tenant via `TenantMiddleware`, which sets `request.tenant` on every request, in this priority order:

1. **Subdomain** — `hertz-albania.bizal.al` → slug `hertz-albania`
2. **Query param** — `localhost:8001/?tenant=hertz-albania` (local dev fallback)
3. **Session** — persisted slug from a previous request on port 8001 (local dev)

| Environment | Main platform | Tenant portal |
|---|---|---|
| Local dev | `localhost:8000` | `localhost:8001/?tenant=x` or `x.localhost:8001` |
| Production | `bizal.al` | `x.bizal.al` |

Resolution outcomes:
- **Main domain** → `request.tenant = None`
- **Tenant subdomain** → `request.tenant = <Tenant instance>` (active, or trial-expired with `is_active=False`)
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
| `settings/local.py` | Local dev (SQLite, no Redis, no Celery) |
| `settings/test.py` | pytest / CI (SQLite locally; real Postgres in CI — see [Testing](#testing)) |
| `settings/production.py` | Docker / production (HTTPS headers, structured logging) |

`DJANGO_SETTINGS_MODULE` is set in `docker-compose.yml` (production) and in `dev.py` / `activate.ps1` (local); it should also be set in `.env` as a safety net.

### Credit Ledger

`Tenant.referral_credits` is the running balance for fast reads. Every change to that balance is mirrored as an append-only `CreditLedger` row (`tenants/models.py`) for audit trail and display. Write credits via `TenantReferral.apply_credit()` only — never mutate `referral_credits` directly.

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

Locally this runs against SQLite (in-memory, no external services required). **CI** (`.github/workflows/tests.yml`) additionally runs the full suite against real **PostgreSQL 16**, specifically to exercise Postgres-only behaviour that SQLite would silently skip: `select_for_update()` locking, `NULLS LAST` ordering, `JSONField` queries, `CheckConstraint` enforcement. CI also enforces `coverage report --fail-under=85` — coverage measured locally (SQLite) at the time of writing is **100%**; the CI run itself (against Postgres) is the authoritative number — check the latest `backend-coverage` artifact on GitHub Actions for the current figure rather than trusting this README.

1332 tests total, all passing, spread across:

| App | Tests | App | Tests |
|---|---|---|---|
| `tenants` | 275 | `accounts` | 110 |
| `chatbot` | 104 | `payments` | 100 |
| `bizal` (dashboard, validators, celery sync, tenant isolation) | 84 | `hotels` | 69 |
| `bookings` | 61 | `billing` | 59 |
| `notifications` | 52 | `orders` | 48 |
| `appointments` | 47 | `reviews` | 46 |
| `storefront` | 40 | `analytics` | 39 |
| `inventory` | 35 | `staff` | 31 |
| `rentals` | 30 | `contact` | 24 |
| `blog` | 16 | `crm` | 16 |
| `activity` | 16 | `menu` | 15 |
| `subscriptions` | 15 | | |

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

Latest committed baseline (dev server, SQLite — worst case, not production): **382 requests, 0% failures, 9ms median / 44ms p95** response time across all endpoint types and tenants. Raw data: `backend/loadtest/results/`.

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
- Add `'myapp'` to `INSTALLED_APPS` in `settings/base.py`
- Add `path('api/myapp/', include('myapp.urls'))` in `bizal/urls.py`
- Run `bizal-migrate`

---

## Notable Design Decisions

- The standalone `superadmin.html` SPA was retired in favor of `/django-admin/` via Unfold's dashboard callbacks.
- Tenant storefront customization is a full drag-and-drop homepage section builder — see [Homepage Page Builder](#homepage-page-builder).
- Shared typography (Cormorant Garamond + DM Sans) and a warm neutral palette are defined once in `brand.css` / `ui.js` / `auth.js` and reused across storefront and tenant admin.
- `CSRF_TRUSTED_ORIGINS` is configured for Django running behind an nginx reverse proxy.
- Chatbot endpoints are covered by a dedicated auth-gate test suite (every endpoint rejects anonymous/expired/malformed JWTs on both main domain and tenant subdomains) plus a frontend Jest harness driving the real chat widget in jsdom.
