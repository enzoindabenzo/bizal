# BizAL — Fix Changelog

## What Was Fixed

### 1. 🔗 URL Persistence on Refresh
**Problem:** Navigating to `#services` or `#menu` then refreshing loaded a different/blank page.

**Fix:**
- All tenant pages now use **hash-based routing** (`#home`, `#services`, `#menu`, etc.)
- The URL stays at `hertz.localhost:8001/#services` — refresh always works
- `tenant_spa` catch-all view in `bizal/views.py` sends ALL tenant subpaths to `index.html`

**Local dev — use subdomains (recommended):**
Add to your `/etc/hosts` (or `C:\Windows\System32\drivers\etc\hosts` on Windows):
```
127.0.0.1  hertz.localhost
127.0.0.1  klinika.localhost
127.0.0.1  restorant.localhost
```
Then visit `http://hertz.localhost:8001/` — URL is always stable. ✓

---

### 2. 🌙 Dark / Light Theme
**Problem:** Theme toggle on tenant pages had no effect — page stayed white.

**Fix:**
- `tenant.js` now initializes theme immediately on load (before any content renders)
- `data-theme="dark"` attribute set on `<html>` from `localStorage`
- All CSS variables correctly respond to `[data-theme="dark"]`
- Both navbar and mobile drawer theme toggles bound to the same handler
- Theme persists across page reloads and sections

---

### 3. 🏢 Per-Tenant Admin Pages
**New file:** `templates/tenant_admin.html`

Each tenant gets their own admin panel at `/admin/` on their subdomain:
- `hertz.localhost:8001/admin/` → Hertz Albania admin
- `klinika.localhost:8001/admin/` → Klinika admin

Features:
- Dashboard with booking stats
- Bookings: confirm, cancel, view details
- Fleet / Services / Menu / Inventory management (auto-detected by business type)
- Customer list (derived from bookings)
- Reviews moderation
- Blog management (Enterprise plan)
- Staff management
- Full settings editor (branding, contact, social links)
- Hash routing inside admin — URL stays at `/admin/#bookings` etc.

---

### 4. 👑 Superadmin Panel
**New file:** `templates/superadmin.html`

The ONE master panel — accessible at:
- `localhost:8000/admin/` or `localhost:8000/superadmin/` (main domain)
- `localhost:8000/superadmin/` (explicit)

Powers:
- View ALL tenants across the platform
- Activate pending tenants (one click)
- Edit any tenant (plan, name, colors, status)
- Delete tenants
- See platform-wide stats

Only users with `is_staff=True` OR `role='superadmin'` can log in.

---

### 5. ✨ Shërbimet (Services) — Fixed Loading
**Problem:** Services section showed endless loading skeletons.

**Fix in `index.js`:**
- Auto-detects business type and calls the correct endpoint:
  - Rental businesses → `/api/rentals/`
  - Appointment businesses → `/api/appointments/services/`
  - Food businesses → redirects to `/api/menu/` (shows menu instead)
  - Product businesses → `/api/inventory/`
- Error state shown if API fails (no more infinite spinner)
- Empty state shown if no items exist yet

---

### 6. 💳 Pricing Updated
- Starter: **€15/muaj** (was different)
- Pro: **€40/muaj** (was different)  
- Enterprise: **€80+/muaj** (was different)
- Annual discounts shown (€12, €32)

---

### 7. 🎨 Professional Styling Upgrade
- Complete CSS rewrite (`style.css`, `main.css`)
- Professional card designs with subtle shadows and hover effects
- Better typography with Inter font
- Consistent spacing and border radius tokens
- Service cards: image, name, description, price, availability badge, book button
- Stats row on dashboard
- Improved modal animations
- Professional sidebar design for both admin panels
- Toast notifications
- Responsive mobile design

---

## File Changes Summary

| File | Change |
|------|--------|
| `frontend/templates/main.html` | Rewritten — new pricing, dark mode, professional design |
| `frontend/templates/index.html` | Rewritten — hash routing, fixed structure |
| `frontend/templates/tenant_admin.html` | **NEW** — per-tenant admin panel |
| `frontend/templates/superadmin.html` | Rewritten — professional superadmin panel |
| `frontend/static/css/style.css` | Complete rewrite — dark/light theme, professional UI |
| `frontend/static/css/main.css` | Complete rewrite — landing page styles |
| `frontend/static/js/tenant.js` | Rewritten — theme fix, branding engine |
| `frontend/static/js/index.js` | Rewritten — hash routing, services fix |
| `backend/bizal/views.py` | Added `admin_panel`, `superadmin_panel`, `tenant_spa` |
| `backend/bizal/urls.py` | Added `/admin/`, `/superadmin/`, SPA catch-all |
| `backend/tenants/middleware.py` | Added subdomain routing for `hertz.localhost` |

