# BizAL — Multi-Tenant SaaS Platform for Albanian SMBs

[![Tests](https://github.com/enzoindabenzo/bizal/actions/workflows/tests.yml/badge.svg)](https://github.com/enzoindabenzo/bizal/actions/workflows/tests.yml)
[![Coverage](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/enzoindabenzo/bizal/main/.github/badges/coverage.json)](https://github.com/enzoindabenzo/bizal/actions/workflows/tests.yml)

BizAL is a Django REST Framework backend powering white-label portals for 25+ Albanian business types (restaurants, hotels, clinics, car rentals, gyms, pharmacies, and more). Each business gets its own branded subdomain and feature set based on their subscription plan.

> See `CHANGELOG.md` for version history and `ARCHITECTURE.md` for design
> notes (tenant resolution, base model hierarchy, feature flags, Celery).

---

## Architecture

```
bizal/
├── backend/               Django project root
│   ├── bizal/             Core settings, URLs, Celery
│   ├── accounts/          JWT auth, user profiles, password reset
│   ├── activity/          Cross-app activity/audit log
│   ├── tenants/           Multi-tenancy, plans, features, middleware
│   ├── appointments/      Calendar-based booking (clinics, spas, gyms)
│   ├── analytics/         Dashboard stats + CSV export (Enterprise)
│   ├── billing/           Invoices + line items for tenant customers
│   ├── blog/              Tenant blog with tags, slugs, view counts
│   ├── bookings/          Generic booking engine (tables, rooms, cars)
│   ├── chatbot/           Storefront chat widget + staff handoff
│   ├── contact/           Contact form with email + in-app notifications
│   ├── crm/               Lead pipeline with notes
│   ├── hotels/            Room types, rooms, seasonal pricing
│   ├── inventory/         Products + categories
│   ├── menu/              Restaurant menu categories + items
│   ├── notifications/     In-app notification system
│   ├── orders/            Storefront cart + order fulfillment
│   ├── payments/          Stripe checkout + webhook handler
│   ├── rentals/           Rental item catalogue + availability
│   ├── reviews/           Customer reviews with approval workflow
│   ├── staff/             Staff roster + weekly schedules
│   ├── storefront/        Homepage page builder, hero slides, custom pages
│   └── subscriptions/     Recurring customer subscriptions
├── frontend/              Static HTML/CSS/JS (multi-page)
├── dev.py                 Local dev launcher (ports 8000 + 8001)
├── activate.ps1           PowerShell dev helpers (Windows)
├── docker-compose.yml     Development stack (DEBUG=True, Dockerfile.dev, runserver)
├── docker-compose.prod.yml  Production stack (Dockerfile, production settings, gunicorn)
├── Dockerfile
├── nginx.conf             # standalone host nginx (VPS/bare-metal)
└── nginx/nginx.conf       # Docker nginx service config
```

### Tenant Resolution

Requests are resolved to a tenant via `TenantMiddleware` in this priority order:

1. **Subdomain** — `hertz-albania.bizal.al` → slug `hertz-albania`
2. **Query param** — `localhost:8001/?tenant=hertz-albania`
3. **Session** — persisted slug from a previous request on port 8001

Main domain (`bizal.al`, port 8000) has no tenant — used for landing page, Django admin, and staff login only.

### Plans & Features

| Feature             | Free | Pro | Enterprise |
|---------------------|------|-----|------------|
| Menu/Services       | ✓    | ✓   | ✓          |
| Bookings            | ✓    | ✓   | ✓          |
| Reviews             | ✓    | ✓   | ✓          |
| Blog                |      | ✓   | ✓          |
| Notifications       |      | ✓   | ✓          |
| CRM / Leads         |      | ✓   | ✓          |
| Staff Management    |      | ✓   | ✓          |
| Invoicing           |      | ✓   | ✓          |
| Analytics Dashboard |      |     | ✓          |
| CSV Export          |      |     | ✓          |
| Custom Pages        |      | ✓   | ✓          |
| Homepage Builder    |      | ✓   | ✓          |

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
bizal-seed               # re-seed demo data
bizal-test               # run all tests
bizal-coverage           # tests + coverage report
bizal-shell              # Django interactive shell
bizal-help               # show all commands
```

### Demo URLs

| URL | Description |
|-----|-------------|
| `http://localhost:8000` | Landing page |
| `http://localhost:8000/admin` | Django admin (`admin@bizal.al` / see password printed by `seed.py` or set `SEED_ADMIN_PASSWORD` in `.env` before running setup) |
| `http://localhost:8001/?tenant=restorant-adriatiku` | Restaurant (Pro) |
| `http://localhost:8001/?tenant=hertz-albania` | Car Rental (Enterprise) |
| `http://localhost:8001/?tenant=klinika-shendeti` | Clinic (Pro) |

---

## API Overview

Base URL: `/api/`

### Auth (`/api/auth/`)
| Method | Path | Auth |
|--------|------|------|
| POST | `register/` | Public |
| POST | `login/` | Public |
| POST | `token/refresh/` | Public |
| POST | `logout/` | ✓ |
| GET/PATCH | `me/` | ✓ |
| POST | `change-password/` | ✓ |
| POST | `password-reset/` | Public |
| POST | `password-reset/confirm/` | Public |

### Tenants (`/api/tenants/`)
`GET /` public profile · `POST /signup/` · `GET|PATCH /me/` owner

### Menu (`/api/menu/`)
Public read · Owner manages categories and items

### Bookings (`/api/bookings/`)
Public create · Owner lists/manages

### Reviews (`/api/reviews/`)
Authenticated create · Public approved list · Owner approves

### Blog (`/api/blog/`)
Public read by slug or tag · Owner manages posts

### Notifications (`/api/notifications/`)
`GET /` · `GET /unread-count/` · `POST /mark-all-read/` · `POST /<pk>/read/`

### Analytics (`/api/analytics/`)
Owner only · `?start_date=&end_date=` · `?export=csv` (Enterprise)

### Storefront (`/api/storefront/`)
`GET pages/` · `GET pages/<slug>/` · `GET hero/` · `GET sections/` (homepage builder blocks) · Owner: `manage/pages/` `manage/hero/` `manage/sections/`

### CRM (`/api/crm/`)
Staff+ · `leads/` · `leads/<pk>/` · `leads/<pk>/notes/`

### Billing (`/api/billing/`)
Staff+ · `invoices/` · `invoices/<pk>/` · `invoices/<pk>/lines/`

### Subscriptions (`/api/subscriptions/`)
Staff+ list · Owner manage · Customer: `mine/`

### Staff (`/api/staff/`)
Staff read · Owner manage

### Inventory (`/api/inventory/`)
`categories/` · `·` list/detail/manage

### Hotels (`/api/hotels/`)
`room-types/` · `room-types/<pk>/` · `room-types/<pk>/seasonal-prices/` · `rooms/`

### Rentals, Appointments, Payments, Contact
Standard CRUD — see individual app `urls.py`

---

## Docker / Production

> **H-2 FIX:** Use `docker-compose.prod.yml` for production deployments.
> `docker-compose.yml` is the **development** stack — it hardcodes `DEBUG=True`,
> `Dockerfile.dev`, and Django's `runserver`. `docker-compose.prod.yml` builds
> from the root `Dockerfile`, uses `bizal.settings.production` (gunicorn, all
> safety guards active), and correctly mounts the media volume into nginx.

```bash
cp .env.example .env                                   # fill in secrets
docker compose -f docker-compose.prod.yml up -d --build  # production
# — or for local development:
docker compose up -d                                   # dev stack
```

**Environment variables (`.env`):**

```
SECRET_KEY=
DEBUG=False
ALLOWED_HOSTS=bizal.al,.bizal.al

DB_NAME=bizal
DB_USER=bizal
DB_PASSWORD=
DB_HOST=db
DB_PORT=5432

REDIS_URL=redis://redis:6379/0         # Celery broker + result
REDIS_CACHE_URL=redis://redis:6379/1   # Django cache

STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=
STRIPE_PRICE_STARTER=price_xxx
STRIPE_PRICE_PRO=price_xxx
STRIPE_PRICE_ENTERPRISE=price_xxx

EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
DEFAULT_FROM_EMAIL=noreply@bizal.al

FRONTEND_BASE_URL=https://bizal.al
```

---

## Testing

```bash
cd backend
python manage.py test                        # all tests
python manage.py test accounts tenants crm   # specific apps
coverage run manage.py test && coverage report --fail-under=85
```

Tests use SQLite in-memory (no external services required).

---

## Adding a New Business Type

1. Add the slug + label to `BUSINESS_TYPE_CHOICES` in `tenants/models.py`
2. Run `bizal-migrate`
3. Add a seed entry in `seed.py` if wanted
4. Any app-specific feature (e.g. `has_feature('table_reservations')`) goes in `TenantFeature` and gets seeded by `apply_plan_defaults()`

---

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