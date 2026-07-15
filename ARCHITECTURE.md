# BizAL — Architecture Notes

## Overview

BizAL is a multi-tenant SaaS platform for Albanian businesses. A single Django
backend serves two logical "zones" — the **main platform** (marketing site,
signup, marketplace) and **tenant spaces** (each business's own subdomain).

> See `CHANGELOG.md` for version history and `README.md` for setup/API docs.

---

## Dual-port / dual-domain design

### Local development

| Port | Domain example             | Purpose                          |
|------|----------------------------|----------------------------------|
| 8000 | `localhost:8000`           | Main platform (marketing, admin) |
| 8001 | `hertz-albania.localhost`  | Tenant portal (via /etc/hosts)   |
| 8001 | `localhost:8001/?tenant=x` | Tenant portal (fallback)         |

Both servers run the same Django process. `TenantMiddleware` routes them by
reading the `Host` header.

### Production

| Domain                     | Purpose                |
|----------------------------|------------------------|
| `bizal.al`                 | Main platform          |
| `hertz-albania.bizal.al`   | Tenant subdomain       |

The middleware distinguishes them: `host == 'bizal.al'` → `request.tenant = None`
(main domain), `host.endswith('.bizal.al')` → slug extracted, tenant resolved.

---

## request.tenant

`TenantMiddleware` sets `request.tenant` on every request.

- **Main domain**: `request.tenant = None`
- **Tenant subdomain**: `request.tenant = <Tenant instance>` (active, or
  trial-expired with `is_active=False`)
- **Unknown slug**: raises `Http404`

All tenant-scoped API views filter querysets by `request.tenant`. Never filter
by `request.user.tenant` in tenant-facing views — use `request.tenant` so the
isolation is enforced at the middleware level, not per-view.

---

## Base model hierarchy

```
models.Model
  └── UUIDModel                    (uuid pk)
  └── TimeStampedModel             (created_at, updated_at)
  └── TenantScopedModel            (non-nullable tenant FK + timestamps)
        └── TenantScopedUUIDModel  (uuid pk + tenant FK + timestamps)  ← use this
```

Every model that belongs to a tenant should inherit from `TenantScopedUUIDModel`
(in `bizal/base_models.py`). Using raw `ForeignKey(Tenant, ...)` directly on a
model is a code smell — it's easy to accidentally make it nullable, which allows
orphaned rows and bypasses the CASCADE guarantee.

---

## Platform vs tenant model split

Some apps have both a **tenant model** (data belonging to one business) and a
**platform model** (data about the platform itself, visible across all tenants).

The canonical example is `reviews/`:

| File                        | Scope                                    |
|-----------------------------|------------------------------------------|
| `reviews/models.py`         | Per-tenant reviews (guests reviewing a business) |
| `reviews/platform_models.py`| Platform reviews (users reviewing BizAL itself) |
| `reviews/platform_views.py` | Views for the platform review endpoints  |
| `reviews/platform_urls.py`  | URL patterns for platform review endpoints |

When an app needs platform-level resources (e.g. platform-wide analytics,
BizAL's own blog, etc.), follow this same pattern rather than inventing a new
one. Keep the platform files in the same app directory — don't create a
separate `platform/` app.

---

## Feature flags

Plan capabilities are stored in `TenantFeature` rows (key/value per tenant).
`Tenant.has_feature('bookings')` is the canonical check. The
`HasTenantFeature('bookings')` permission class uses it.

`apply_plan_defaults()` is called from `Tenant.save()` whenever the plan or
business type changes. It uses `bulk_create(..., update_conflicts=True)` — a
single DB round-trip replaces the old N×`update_or_create` loop.

Custom grants (`is_custom_grant=True`) are set by superadmins and are never
overwritten by plan changes.

---

## Middleware prefetch caching

`TenantMiddleware._get_tenant()` caches the resolved `Tenant` object in Redis
for 5 minutes. The cached object is populated via
`prefetch_related('features', 'locations')` before being stored, so
`tenant.has_feature()` iterates an in-memory list rather than hitting the DB.

On cache hit, the Python object from `cache.get()` already has
`_result_cache` populated on the `features` queryset — `has_feature()` calls
`self.features.all()` which returns the cached list rather than issuing a new
query.

---

## Celery

- **Worker**: `celery -A bizal worker`
- **Beat**: `celery -A bizal beat --scheduler django_celery_beat.schedulers:DatabaseScheduler`
- Periodic tasks are defined in `settings/base.py` under `CELERY_BEAT_SCHEDULE`.
- The DB-backed scheduler (`django_celery_beat`) persists last-run timestamps
  across container restarts. Without it, all periodic tasks run immediately on
  every beat container restart.

---

## Settings modules

| Module              | Used when                               |
|---------------------|-----------------------------------------|
| `settings/base.py`  | Shared config inherited by all          |
| `settings/local.py` | Local dev (SQLite, no Redis, no Celery) |
| `settings/test.py`  | pytest / CI (SQLite in-memory, DummyCache) |
| `settings/production.py` | Docker / production (HTTPS headers, LOGGING) |

`DJANGO_SETTINGS_MODULE` is set in `docker-compose.yml` (production) and in
`dev.py` / `activate.ps1` (local). It should also be set in `.env` as a
safety net.

---

## Credit ledger

`Tenant.referral_credits` is the running balance for fast reads. Every change
to that balance is mirrored as an append-only `CreditLedger` row
(`tenants/models.py`) for audit trail and display. Write credits via
`TenantReferral.apply_credit()` only — never mutate `referral_credits` directly.

---

## Homepage page builder (`storefront.StorefrontSection`)

The tenant homepage is built from an ordered list of `StorefrontSection`
rows, each with a `section_type` (text, image, cta, gallery, features,
testimonial, spacer). Shared fields (`title`, `subtitle`, `body`, `image`,
`cta_label`, `cta_url`, `background_color`) cover most block types directly;
anything that needs a variable-length list (gallery image URLs, feature
items) goes in the `data` JSONField instead of a separate table per type.
This keeps adding a new block type a matter of extending
`SECTION_TYPE_LABELS`/`sectionTypeFields()` on the frontend and a
`data`-shape check in `StorefrontSectionSerializer.validate_data()` on the
backend — no new model or migration needed unless a type needs a field
that doesn't fit the shared shape.

Reordering (sections, hero slides, and extra pages) all share one frontend
pattern: `initReorder()` in `tenant_admin.html` wires up drag handles and
▲▼ buttons on a `<tbody>`, then persists via serialized PATCH `order`
writes to `endpoint{id}/` — see the "Rapid drags/clicks" comment above
`initReorder` for why the persist calls are serialized rather than fired
concurrently. Any new reorderable list should reuse `initReorder()` rather
than reimplementing drag-and-drop.

---

## JWT storage (frontend)

Access and refresh tokens are stored in `localStorage` in the tenant SPA
(`index.html`). This is a deliberate tradeoff — see the `Auth` object comment
in `index.html` for the reasoning and the conditions under which it should
be revisited.
