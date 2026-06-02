# BizAL — Multi-Tenant SaaS Platform for Albanian SMEs

A production-grade, multi-tenant SaaS platform built with **Django** and pure **HTML/CSS/JavaScript** (no React, no Node.js build step). Each business gets its own branded subdomain portal, isolated data, and admin panel — all served from a single Django instance.

```
restorant-adriatiku.bizal.al  →  Restaurant portal
hertz-albania.bizal.al        →  Car rental portal
klinika-shendeti.bizal.al     →  Clinic portal
bizal.al                      →  Main marketing & signup page
```

![Tests](https://github.com/your-org/BizAL/actions/workflows/test.yml/badge.svg)

---

## Supported Business Types (25+)

| Category | Types |
|----------|-------|
| 🍽️ Food & Hospitality | Restaurant, Hotel, Bar, Delivery Kitchen, Bakery |
| 🛍️ Retail & Commerce | Market, Pharmacy, Electronics, Clothing, Organic |
| 🚗 Rentals | Car, Property, Equipment, Boat |
| 💆 Health & Beauty | Barbershop, Spa, Gym, Clinic, Tattoo Studio |
| 🔧 Services | Auto Repair, Cleaning, Lawyer, Accounting, Events |
| 🎓 Education | Language School, Tutoring, Driving School, Coding Bootcamp |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Django 4.2, Django REST Framework |
| Auth | JWT (SimpleJWT) with refresh rotation + blacklisting |
| Database | PostgreSQL |
| Cache | Redis |
| Queue | Celery |
| Payments | Stripe (subscriptions + webhooks) |
| Static | WhiteNoise |
| Server | Gunicorn + Nginx |
| Frontend | Django Templates + Vanilla JS (no build step) |

---

## Quick Start

**Prerequisites:** Python 3.10+, PostgreSQL, Redis

```bash
git clone https://github.com/your-org/BizAL.git
cd BizAL
```

**Windows:**
```bash
python setup.py
```

**Mac / Linux:**
```bash
python3 setup.py
```

Then:
```bash
cd backend
python manage.py runserver
```

---

## Local Dev — Two Ports, No Confusion

**Port 8000 = main domain. Port 8001 = tenant portal. Always. No overlap.**

Start both servers with one command:
```bash
python dev.py
```

Or start them manually in two terminals:
```bash
# Terminal 1
python backend/manage.py runserver 8000   # main domain

# Terminal 2
python backend/manage.py runserver 8001   # tenant portal
```

| URL | What you get |
|-----|-------------|
| `http://localhost:8000` | Main domain — landing page, pricing, signup |
| `http://localhost:8000/admin` | Superadmin panel |
| `http://localhost:8001/?tenant=restorant-adriatiku` | Restaurant portal |
| `http://localhost:8001/?tenant=hertz-albania` | Car rental portal |
| `http://localhost:8001/?tenant=klinika-shendeti` | Clinic portal |

### How it works

The middleware reads the **port** from the `Host` header:

```
localhost:8000  →  request.tenant = None   (main domain)
localhost:8001  →  request.tenant = <Tenant from ?tenant=slug>
```

No subdomain entries in `/etc/hosts` needed for dev.  
In production it switches to subdomain resolution automatically:

```
bizal.al              →  main domain
hertz.bizal.al        →  Hertz tenant
klinika.bizal.al      →  Clinic tenant
```

---

## Tenant System

`TenantMiddleware` resolves the subdomain on every request and attaches the tenant to `request.tenant`. All querysets are automatically scoped.

```
hertz-albania.bizal.al  →  request.tenant = <Tenant: Hertz Albania>
bizal.al                →  request.tenant = None  (main domain)
unknown.bizal.al        →  404
inactive.bizal.al       →  404
```

### Plan Feature Matrix

| Feature | Starter | Pro | Enterprise |
|---------|---------|-----|-----------|
| Custom branding | ✗ | ✓ | ✓ |
| Contact form | ✗ | ✓ | ✓ |
| WhatsApp button | ✗ | ✓ | ✓ |
| Analytics | ✗ | ✓ | ✓ |
| Reviews | ✗ | ✓ | ✓ |
| Staff accounts (5) | ✗ | ✓ | ✓ |
| Blog | ✗ | ✗ | ✓ |
| Payments online | ✗ | ✗ | ✓ |
| CRM | ✗ | ✗ | ✓ |
| CSV / PDF export | ✗ | ✗ | ✓ |
| API access | ✗ | ✗ | ✓ |

---

## API Reference

### Auth
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/register/` | Register — rate limited 5/min |
| POST | `/api/auth/login/` | Login — rate limited 5/min |
| POST | `/api/auth/token/refresh/` | Refresh access token |
| POST | `/api/auth/logout/` | Blacklist refresh token |
| GET/PATCH | `/api/auth/me/` | Profile |

### Tenant
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/tenant/info/` | Public tenant branding info |
| GET/PATCH | `/api/tenant/settings/` | Owner edits settings |
| POST | `/api/tenant/signup/` | Register new business |
| GET | `/api/tenant/check-slug/` | Check subdomain availability |

### Bookings
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET/POST | `/api/bookings/` | List / create bookings |
| GET | `/api/bookings/<id>/` | Booking detail |
| POST | `/api/bookings/<id>/cancel/` | Cancel |
| PATCH | `/api/bookings/<id>/admin-update/` | Admin update |

### Rentals
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/rentals/` | List rental items |
| GET | `/api/rentals/<id>/` | Item detail |
| GET | `/api/rentals/<id>/availability/` | Check availability |
| POST | `/api/rentals/create/` | Owner: add item |

### Appointments
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/appointments/providers/` | List providers |
| GET | `/api/appointments/services/` | List services |
| POST | `/api/appointments/` | Book appointment |
| GET | `/api/appointments/admin/` | Admin: all appointments |

### Menu (Restaurants)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/menu/` | Full menu with categories |
| POST | `/api/menu/items/` | Owner: add item |
| PATCH/DELETE | `/api/menu/items/<id>/` | Owner: manage item |

### Reviews
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/reviews/` | List reviews (public) |
| POST | `/api/reviews/` | Submit review (authenticated) |

### Blog
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/blog/` | Published posts |
| GET | `/api/blog/<slug>/` | Post detail |
| GET | `/api/blog/tags/` | Tags |

### Analytics
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/analytics/` | Metrics dashboard (Pro+) |
| GET | `/api/analytics/?export=csv` | CSV export (Enterprise) |

### Payments
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/payments/subscribe/` | Stripe subscription checkout |
| POST | `/api/payments/webhook/` | Stripe webhook receiver |

---

## Running Tests

```bash
cd backend

# Full suite with coverage
coverage run --rcfile=.coveragerc manage.py test --settings=bizal.settings.test
coverage report --rcfile=.coveragerc --show-missing

# Specific app
python manage.py test tenants --settings=bizal.settings.test
python manage.py test reviews --settings=bizal.settings.test
python manage.py test accounts --settings=bizal.settings.test

# Parallel (faster)
python manage.py test --settings=bizal.settings.test --parallel
```

---

## Production Deployment

### Docker
```bash
cp .env.example .env
# Fill in your values in .env
docker-compose up -d
docker-compose exec web python manage.py migrate
docker-compose exec web python manage.py createsuperuser
```

### DNS (Cloudflare)
```
bizal.al        → A → your-server-ip
*.bizal.al      → A → your-server-ip  (wildcard)
```

### Stripe Webhooks
Register `https://bizal.al/api/payments/webhook/` and subscribe to:
- `checkout.session.completed`
- `customer.subscription.updated`
- `customer.subscription.deleted`

---

## Project Structure

```
BizAL/
├── backend/
│   ├── bizal/               # Django project settings, urls, celery
│   ├── tenants/             # Multi-tenant engine + middleware
│   ├── accounts/            # Custom user model + JWT auth
│   ├── bookings/            # Generic booking engine
│   ├── appointments/        # Clinics, salons, gyms
│   ├── menu/                # Restaurants
│   ├── hotels/              # Hotel rooms + availability
│   ├── rentals/             # Cars, boats, equipment
│   ├── inventory/           # Shops + pharmacies
│   ├── analytics/           # Per-tenant metrics
│   ├── reviews/             # Tenant-isolated reviews
│   ├── blog/                # Tenant blog system
│   ├── payments/            # Stripe integration
│   ├── contact/             # Contact forms
│   ├── notifications/       # In-app notifications
│   ├── billing/             # Subscription management
│   ├── staff/               # Staff management
│   ├── crm/                 # Customer relationship
│   ├── storefront/          # Public storefront API
│   ├── subscriptions/       # Plan management
│   ├── seed.py              # Demo data
│   └── requirements.txt
├── frontend/
│   ├── templates/
│   │   ├── index.html       # Tenant SPA
│   │   └── main.html        # Main domain landing page
│   └── static/
│       ├── css/
│       │   ├── style.css    # Core styles
│       │   ├── index.css    # Tenant portal extras
│       │   └── main.css     # Landing page styles
│       └── js/
│           ├── app.js       # Shared utilities + API client
│           ├── tenant.js    # Branding engine
│           ├── index.js     # Tenant SPA entry
│           └── main.js      # Landing page scripts
├── .github/workflows/
│   └── test.yml             # CI — runs tests on every push
├── Dockerfile
├── docker-compose.yml
├── nginx.conf
├── setup.py
└── .env.example
```

---

## Security

- JWT refresh token rotation + blacklisting
- Cross-tenant JWT rejection (token from tenant A rejected on tenant B)
- Rate limiting on all auth endpoints (5 req/min per IP via Redis)
- Main domain login restricted to staff/superusers
- Tenant isolation enforced at middleware + queryset level
- CSRF protection on all mutations
- WhiteNoise for static files (no user-served content from Django)
- Stripe webhook signature verification
- Raw Stripe errors never exposed to clients

---

Built with ❤️ for Albanian SMEs.
