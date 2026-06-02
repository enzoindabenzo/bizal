"""
BizAL — Core Views v2
=====================
All tenant pages now served by ONE template (index.html).
Hash-based routing (#services, #menu, etc.) handles sections client-side,
so the URL stays at `hertz.localhost:8001/` on refresh.

Admin panels:
  - /admin/          → tenant admin  (owner/manager access)
  - /superadmin/     → superadmin    (is_staff access only)
"""
from django.shortcuts import render
from django.http import Http404


def home(request):
    """
    Main entry point.
    - No tenant (main domain / port 8000) → landing page
    - Tenant domain / port 8001           → SPA shell
    All sections (#home, #services, #menu …) are rendered
    client-side via JS — no separate page loads needed.
    """
    if not request.tenant:
        return render(request, 'main.html')
    return render(request, 'index.html', {'tenant': request.tenant})


def tenant_spa(request):
    """
    Catch-all for any path under a tenant domain.
    Redirects deep-links back to the SPA root so that
    navigating to /services/ or /menu/ still loads correctly.
    """
    if not request.tenant:
        raise Http404("This page requires a tenant.")
    return render(request, 'index.html', {'tenant': request.tenant})


def admin_panel(request):
    """
    Tenant admin panel.
    Served at /admin/ on the tenant subdomain.
    Auth and role-checking is done client-side via JWT.
    """
    if not request.tenant:
        # On main domain, redirect to superadmin
        return render(request, 'superadmin.html')
    return render(request, 'tenant_admin.html', {'tenant': request.tenant})


def superadmin_panel(request):
    """
    Superadmin panel — accessible only from the main domain.
    Controls ALL tenants.
    """
    return render(request, 'superadmin.html')
