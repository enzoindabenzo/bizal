"""
BizAL — URL Configuration v2

Key changes vs v1:
  • /admin/          serves tenant_admin.html on a tenant subdomain;
                     redirects to /django-admin/ on the main domain
  • /django-admin/   Django admin + Unfold — the single platform-admin
                     surface. Restricted to the main domain (see
                     TenantMiddleware._enforce_admin_main_domain_only).
                     Its index page carries a KPI + analytics dashboard
                     (bizal/dashboard.py).
  • /onboarding/     serves 6-step setup wizard after signup
  • /account/        no dedicated view anymore — falls through to the
                     catch-all like any other path, so it renders the
                     normal SPA shell (main.html on the main domain,
                     index.html on a tenant subdomain). main.html's client
                     router recognises the bare '/account/' path and opens
                     the in-page profile section (see main.html's boot IIFE);
                     index.html already has its own inline profile section
                     regardless of path. account.html was removed — its
                     essential (non-tenant-scoped) functionality — profile
                     edit, password change, notification prefs, account
                     deletion — was merged into main.html's pg-profile page.
  • /login/          served by main.html shell on main domain (JS router)
  • /signup/         served by main.html shell on main domain (JS router)
  • All other tenant paths → SPA catch-all (index.html)
    so that /services/, /menu/ etc. still work with JS routing
"""
from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from .views import home, admin_panel, tenant_spa, onboarding, robots_txt, sitemap_xml, health_check

# Branding for the built-in Django admin (see frontend/templates/admin/base_site.html
# and frontend/static/css/admin_theme.css for the visual theme override).
admin.site.site_header = 'BizAL Admin'
admin.site.site_title = 'BizAL Admin'
admin.site.index_title = 'Platform administration'

urlpatterns = [
    # ── Django built-in admin (moved) ─────────────────────────
    path('django-admin/', admin.site.urls),

    # ── Custom admin panel ──────────────────────────────────────
    path('admin/', admin_panel, name='admin-panel'),

    # ── Onboarding wizard (post-signup) ───────────────────────
    path('onboarding/', onboarding, name='onboarding'),

    # ── SPA shell + dedicated page views ──────────────────────
    path('health/', health_check, name='health-check'),
    path('robots.txt', robots_txt,  name='robots-txt'),
    path('sitemap.xml', sitemap_xml, name='sitemap-xml'),

    path('',         home,    name='home'),
    path('login/',   home,    name='login'),
    path('signup/',  home,    name='signup'),
    # /trial-expired/ deliberately serves the same `home` view as every
    # other tenant page, NOT a dedicated server-side "trial expired"
    # template. On a tenant subdomain this renders index.html — the same
    # SPA shell as any other tenant page — which then calls
    # GET /api/tenants/info/, reads `trial_expired`/`is_active`, and
    # renders the upgrade screen client-side. This route exists purely so
    # links like {FRONTEND_BASE_URL}/trial-expired/ (e.g. from the Celery
    # trial-expiry email) land somewhere that resolves to the tenant SPA
    # rather than 404ing; the actual "your trial has expired" UI is
    # entirely client-side, not server-rendered here.
    path('trial-expired/', home, name='trial-expired'),

    # Catch-all: any unrecognised path returns the appropriate SPA shell.
    # Explicit Django-managed paths are excluded so they still resolve correctly.
    re_path(
        r'^(?!api/|admin/|django-admin/|onboarding/|login/|signup/|trial-expired/|static/|media/).*$',
        tenant_spa,
        name='tenant-spa',
    ),

    # ── REST API ───────────────────────────────────────────────
    path('api/auth/',             include('accounts.urls')),
    path('api/tenants/',          include('tenants.urls')),
    path('api/activity/',         include('activity.urls')),
    path('api/billing/',          include('billing.urls')),
    path('api/payments/',         include('payments.urls')),
    path('api/bookings/',         include('bookings.urls')),
    path('api/appointments/',     include('appointments.urls')),
    path('api/menu/',             include('menu.urls')),
    path('api/hotels/',           include('hotels.urls')),
    path('api/rentals/',          include('rentals.urls')),
    path('api/inventory/',        include('inventory.urls')),
    path('api/analytics/',        include('analytics.urls')),
    path('api/reviews/',          include('reviews.urls')),
    path('api/platform-reviews/', include('reviews.platform_urls')),
    path('api/blog/',             include('blog.urls')),
    path('api/contact/',          include('contact.urls')),
    path('api/notifications/',    include('notifications.urls')),
    path('api/staff/',            include('staff.urls')),
    path('api/storefront/',       include('storefront.urls')),
    path('api/crm/',              include('crm.urls')),
    path('api/subscriptions/',    include('subscriptions.urls')),
    path('api/orders/',           include('orders.urls')),
    path('api/chatbot/',          include('chatbot.urls')),

] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)