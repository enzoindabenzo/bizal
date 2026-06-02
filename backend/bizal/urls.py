"""
BizAL — URL Configuration v2

Key changes vs v1:
  • /admin/          serves tenant_admin.html (not Django admin)
  • /django-admin/   serves Django admin (moved out of the way)
  • /superadmin/     serves superadmin.html on main domain
  • All other tenant paths → SPA catch-all (index.html)
    so that /services/, /menu/ etc. still work with JS routing
"""
from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from .views import home, admin_panel, superadmin_panel, tenant_spa


urlpatterns = [
    # ── Django built-in admin (moved) ─────────────────────────
    path('django-admin/', admin.site.urls),

    # ── Custom admin panels ────────────────────────────────────
    # Tenant admin: hertz.localhost:8001/admin/
    # Main domain:  localhost:8000/admin/  → superadmin
    path('admin/', admin_panel, name='admin-panel'),

    # Superadmin (explicit URL, also reachable from /admin/ on main domain)
    path('superadmin/', superadmin_panel, name='superadmin-panel'),

    # ── SPA shell ──────────────────────────────────────────────
    # Root serves landing (main) or tenant SPA (tenant subdomain)
    path('', home, name='home'),

    # Catch-all: any path on a tenant subdomain returns the SPA
    # so that e.g. hertz.localhost:8001/services/ still works
    re_path(r'^(?!api/|admin/|superadmin/|django-admin/|static/|media/).*$', tenant_spa, name='tenant-spa'),

    # ── REST API ───────────────────────────────────────────────
    path('api/auth/',          include('accounts.urls')),
    path('api/tenant/',        include('tenants.urls')),
    path('api/billing/',       include('billing.urls')),
    path('api/payments/',      include('payments.urls')),
    path('api/bookings/',      include('bookings.urls')),
    path('api/appointments/',  include('appointments.urls')),
    path('api/menu/',          include('menu.urls')),
    path('api/hotels/',        include('hotels.urls')),
    path('api/rentals/',       include('rentals.urls')),
    path('api/inventory/',     include('inventory.urls')),
    path('api/analytics/',     include('analytics.urls')),
    path('api/reviews/',       include('reviews.urls')),
    path('api/blog/',          include('blog.urls')),
    path('api/contact/',       include('contact.urls')),
    path('api/notifications/', include('notifications.urls')),
    path('api/staff/',         include('staff.urls')),
    path('api/storefront/',    include('storefront.urls')),
    path('api/crm/',           include('crm.urls')),

] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
