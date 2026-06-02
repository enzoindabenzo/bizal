"""
BizAL — Tenant Middleware v2
=============================
Resolves which tenant is active from the request.

LOCAL DEV — Two strategies supported:

  Strategy A (Recommended): Subdomain via /etc/hosts
  ─────────────────────────────────────────────────────
  Add to /etc/hosts (Mac/Linux) or C:\Windows\System32\drivers\etc\hosts (Windows):
      127.0.0.1  hertz.localhost
      127.0.0.1  klinika.localhost
      127.0.0.1  restorant.localhost
      (etc.)

  Then visit:  http://hertz.localhost:8001/
  The URL stays as-is on every refresh. ✓

  Strategy B (Fallback): ?tenant= query param / session
  ─────────────────────────────────────────────────────
  Visit:  http://localhost:8001/?tenant=hertz-albania
  Slug saved in session → subsequent requests (API calls,
  refreshes) reuse the same tenant without the param.

PRODUCTION:
  hertz.bizal.al  → slug = "hertz"  (subdomain of bizal.al)
"""
from django.http import Http404
from django.core.cache import cache
from .models import Tenant

MAIN_DOMAIN  = 'bizal.al'
LOCAL_DOMAIN = 'localhost'
MAIN_PORT    = 8000
TENANT_PORT  = 8001
SESSION_KEY  = 'bizal_tenant_slug'


class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.tenant = self._resolve_tenant(request)
        return self.get_response(request)

    def _resolve_tenant(self, request):
        host_header = request.get_host().lower()

        # Split host and port
        if ':' in host_header:
            host, port_str = host_header.rsplit(':', 1)
            try:
                port = int(port_str)
            except ValueError:
                port = 80
        else:
            host = host_header
            port = 80

        # ── PRODUCTION ──────────────────────────────────────────
        if host == MAIN_DOMAIN or host == f'www.{MAIN_DOMAIN}':
            return None  # main domain, no tenant

        if host.endswith(f'.{MAIN_DOMAIN}'):
            slug = host[:-(len(MAIN_DOMAIN) + 1)]
            return self._get_tenant(slug, strict=True)

        # ── LOCAL DEV ────────────────────────────────────────────

        # Strategy A: subdomain of localhost
        #   hertz.localhost:8001  →  slug = "hertz"
        #   also supports hertz.localhost:8001 (no port in host header)
        if host.endswith(f'.{LOCAL_DOMAIN}'):
            slug = host[:-(len(LOCAL_DOMAIN) + 1)]
            if slug and slug not in ('www', ''):
                return self._get_tenant(slug, strict=True)

        is_main_local = host in (LOCAL_DOMAIN, '127.0.0.1', '0.0.0.0')

        if is_main_local:
            if port == MAIN_PORT:
                return None  # main landing page

            if port == TENANT_PORT:
                # Strategy B: ?tenant=slug sets the session
                slug = request.GET.get('tenant', '').strip()
                if slug:
                    request.session[SESSION_KEY] = slug
                    request.session.modified = True
                else:
                    slug = request.session.get(SESSION_KEY, '').strip()

                if not slug:
                    # Give a helpful error in dev
                    raise Http404(
                        'Tenant portal: visit with ?tenant=<slug> first.\n'
                        'Example: http://localhost:8001/?tenant=hertz-albania\n\n'
                        'OR add to /etc/hosts:\n'
                        '  127.0.0.1  hertz-albania.localhost\n'
                        'Then visit: http://hertz-albania.localhost:8001/'
                    )
                return self._get_tenant(slug, strict=False)

        return None

    def _get_tenant(self, slug, strict=True):
        """
        Load tenant by slug from cache or DB.
        strict=True  → raises Http404 for inactive tenants
        strict=False → returns tenant even if inactive (allows admin login)
        """
        if not slug:
            return None

        cache_key = f'tenant:{slug}'
        tenant = cache.get(cache_key)

        if tenant is None:
            try:
                tenant = Tenant.objects.prefetch_related('features').get(slug=slug)
                # Cache active tenants for 5 minutes
                if tenant.is_active:
                    cache.set(cache_key, tenant, 300)
            except Tenant.DoesNotExist:
                raise Http404(f'No tenant found for slug: "{slug}"')

        if strict and not tenant.is_active:
            raise Http404(
                f'Tenant "{slug}" is not yet active. '
                f'Contact support or wait for activation.'
            )

        return tenant
