"""
BizAL — Core Views v2
=====================
All tenant pages now served by ONE template (index.html).
Hash-based routing (#services, #menu, etc.) handles sections client-side,
so the URL stays at `hertz.localhost:8001/` on refresh.

Admin panels:
  - /admin/        → tenant admin (owner/manager access) on a tenant subdomain;
                     redirects to /django-admin/ on the main domain.
  - /django-admin/ → the platform-admin surface (Django admin + Unfold +
                     a custom KPI/analytics dashboard). Restricted to the
                     main domain by
                     TenantMiddleware._enforce_admin_main_domain_only().
"""
from django.shortcuts import render
from django.http import HttpResponseRedirect
from django.conf import settings as _s


def home(request):
    """
    Main entry point.
    - No tenant (main domain / port 8000) → landing page (main.html)
    - Tenant subdomain / port 8001        → SPA shell   (index.html)
    """
    if request.tenant:
        return render(request, 'index.html')
    return render(request, 'main.html', {'demo_base_url': getattr(_s, 'DEMO_BASE_URL', '')})


def tenant_spa(request):
    """
    Catch-all for any unrecognised path.

    - Tenant subdomain → index.html  (JS router handles /services/, /menu/ etc.)
    - Main domain      → main.html   (JS router handles /login/, /signup/ etc.)
    """
    if request.tenant:
        return render(request, 'index.html', {'tenant': request.tenant})
    return render(request, 'main.html', {'demo_base_url': getattr(_s, 'DEMO_BASE_URL', '')})


def admin_panel(request):
    """
    /admin/ on tenant subdomain → tenant_admin.html  (owner/manager)
    /admin/ on main domain      → redirect to /django-admin/, the single
                                  platform-admin surface (Django sessions,
                                  not the JWT/localStorage gate used by
                                  tenant panels).
    """
    if request.tenant:
        return render(request, 'tenant_admin.html', {'tenant': request.tenant})
    return HttpResponseRedirect('/django-admin/')


def onboarding(request):
    """
    6-step business setup wizard served at /onboarding/ after signup.
    Auth and PATCH calls are handled client-side via JWT stored in localStorage.
    """
    return render(request, 'onboarding.html')

# ── robots.txt ────────────────────────────────────────────────────────────────

def robots_txt(request):
    """
    Serve /robots.txt.  Blocks crawlers from internal/admin paths while
    allowing indexing of public tenant pages and the marketplace.

    LOW-4 FIX: Return a tenant-aware robots.txt. The old version returned
    the same body on every domain, including the main domain sitemap URL on
    tenant subdomains — misleading to crawlers and incorrect for SEO.
    """
    from django.http import HttpResponse
    if request.tenant:
        # Tenant subdomain — allow all public pages, point to tenant sitemap.
        # LOW-1 FIX: derive scheme from the request so that during the
        # pre-TLS HTTP-only deployment phase the Sitemap URL is reachable.
        # Hardcoding https:// caused crawlers to see a connection-refused
        # error when fetching the sitemap from an HTTP-only server.
        _scheme = request.scheme
        # MEDIUM-3 FIX: sitemap_xml() always builds canonical URLs from
        # FRONTEND_BASE_URL (main domain), not request.get_host(). A Sitemap
        # declaration on hertz.bizal.al pointing at hertz.bizal.al/sitemap.xml
        # is a cross-domain mismatch — Google Search Console flags it and some
        # crawlers ignore it. Use the main-domain URL so the declaration and
        # the sitemap content share the same authority.
        from django.conf import settings as _dj_settings
        _main = getattr(_dj_settings, 'FRONTEND_BASE_URL', '').rstrip('/')
        _sitemap_url = (
            f'{_main}/sitemap.xml'
            if _main
            else f'{_scheme}://{request.get_host()}/sitemap.xml'
        )
        lines = [
            'User-agent: *',
            'Disallow: /admin/',
            'Disallow: /account/',
            'Disallow: /onboarding/',  # MED-5 FIX: block onboarding on tenant subdomains
            '',
            f'Sitemap: {_sitemap_url}',
        ]
    else:
        # Main domain — block internal/admin/onboarding paths.
        _scheme = request.scheme
        lines = [
            'User-agent: *',
            'Disallow: /api/',
            'Disallow: /django-admin/',
            'Disallow: /admin/',
            'Disallow: /onboarding/',
            'Disallow: /account/',
            '',
            f'Sitemap: {_scheme}://{request.get_host()}/sitemap.xml',
        ]
    return HttpResponse('\n'.join(lines), content_type='text/plain')


# ── sitemap.xml ───────────────────────────────────────────────────────────────

def sitemap_xml(request):
    """
    Dynamic sitemap for the main domain listing all active marketplace tenants.
    Tenant subdomains should serve their own sitemap via their SPA.
    """
    from django.http import HttpResponse
    from django.utils import timezone
    from urllib.parse import urlparse
    try:
        from tenants.models import Tenant
        tenants = Tenant.objects.filter(
            is_active=True, listed_on_marketplace=True
        ).values('slug', 'updated_at').order_by('-updated_at')[:10000]
    except Exception:
        tenants = []

    # HIGH-2 FIX: Always derive the sitemap authority from FRONTEND_BASE_URL
    # (the main platform domain) rather than request.get_host(). When a crawler
    # discovers the sitemap URL from a tenant subdomain's robots.txt, get_host()
    # returns e.g. "hertz.bizal.al" and every tenant entry becomes
    # "slug.hertz.bizal.al" — a double-subdomain that resolves to nothing.
    # Using FRONTEND_BASE_URL ensures canonical URLs regardless of which domain
    # the request arrived on.
    _base_url = getattr(_s, 'FRONTEND_BASE_URL', '').rstrip('/')
    if _base_url:
        _parsed = urlparse(_base_url)
        scheme = _parsed.scheme or request.scheme
        host = _parsed.netloc  # e.g. "bizal.al" (no spurious subdomain)
    else:
        scheme = request.scheme
        host = request.get_host()

    base = f'{scheme}://{host}'
    urls = [
        f'<url><loc>{base}/</loc><changefreq>daily</changefreq><priority>1.0</priority></url>',
        f'<url><loc>{base}/marketplace/</loc><changefreq>daily</changefreq><priority>0.9</priority></url>',
    ]
    for t in tenants:
        lastmod = t['updated_at'].strftime('%Y-%m-%d') if t.get('updated_at') else timezone.now().strftime('%Y-%m-%d')
        urls.append(
            f'<url><loc>{scheme}://{t["slug"]}.{host}/</loc>'
            f'<lastmod>{lastmod}</lastmod>'
            f'<changefreq>weekly</changefreq><priority>0.7</priority></url>'
        )

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + '\n'.join(urls)
        + '\n</urlset>'
    )
    return HttpResponse(xml, content_type='application/xml')


# ── Health check ──────────────────────────────────────────────────────────────

def health_check(request):
    """
    GET /health/

    Returns 200 OK with JSON payload when the app is healthy (Django up +
    DB reachable).  Returns 503 if the DB connection fails so that Docker,
    Kubernetes, and load-balancer health probes can distinguish a running
    container from a healthy one.

    This endpoint intentionally requires no authentication so that probes
    work without credentials.
    """
    import json
    from django.http import HttpResponse
    from django.db import connection, OperationalError

    try:
        # L-3 FIX: connection.ensure_connection() was deprecated in Django 4.2
        # and removed in Django 5.0. A Django major-version upgrade would cause
        # every health probe to receive AttributeError → HTTP 500, pulling all
        # containers out of rotation immediately after the upgrade. The replacement
        # — connection.cursor().execute("SELECT 1") — is stable across all
        # supported Django versions (2.x through 5.x) and exercises the full
        # query path rather than just verifying the socket can be opened.
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        db_ok = True
    except OperationalError:
        db_ok = False

    payload = {'status': 'ok' if db_ok else 'degraded', 'db': db_ok}
    http_status = 200 if db_ok else 503
    return HttpResponse(
        json.dumps(payload),
        content_type='application/json',
        status=http_status,
    )
