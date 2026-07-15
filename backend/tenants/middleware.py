"""
BizAL — Tenant Middleware v3
=============================
Resolves which tenant is active from the request.
Also enforces trial expiry — expired trial tenants are treated as inactive.

LOCAL DEV — Two strategies supported:

  Strategy A (Recommended): Subdomain via /etc/hosts
  ─────────────────────────────────────────────────────
  Add to /etc/hosts:
      127.0.0.1  hertz.localhost
      127.0.0.1  klinika.localhost
  Then visit:  http://hertz.localhost:8001/

  Strategy B (Fallback): ?tenant= query param / session
  ─────────────────────────────────────────────────────
  Visit:  http://localhost:8001/?tenant=hertz-albania

PRODUCTION:
  hertz.bizal.al  → slug = "hertz"  (subdomain of bizal.al)
"""
from django.http import Http404
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from .models import Tenant, PLAN_TRIAL

MAIN_DOMAIN  = 'bizal.al'
LOCAL_DOMAIN = 'localhost'
MAIN_PORT    = 8000
TENANT_PORT  = 8001
SESSION_KEY  = 'bizal_tenant_slug'

# Paths that bypass strict active-check (webhook, healthcheck).
# M-4 FIX: '/api/tenants/trial-expired' removed — this API path does not exist
# in urls.py and never did. The actual trial-expired experience is '/trial-expired/'
# (a frontend SPA route in bizal/urls.py), which requires no middleware bypass
# because it's a static HTML serve, not a tenant-resolved API call. The dead
# bypass entry was misleading: developers could add a real endpoint at that path
# not realising it already bypasses tenant resolution (request.tenant = None).
STRICT_BYPASS_PATHS = (
    '/api/payments/webhook',
    '/health',                    # CRIT-1 FIX: healthcheck must bypass tenant resolution
)
# L-2 FIX: pre-compute the stripped set once at module load instead of
# rebuilding it on every HTTP request inside _resolve_tenant().
_BYPASS_SET = {p.rstrip('/') for p in STRICT_BYPASS_PATHS}


class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.tenant = self._resolve_tenant(request)
        self._enforce_trial(request)
        self._enforce_admin_main_domain_only(request)
        return self.get_response(request)

    def _enforce_admin_main_domain_only(self, request):
        """
        /django-admin/ was merged with the old standalone superadmin.html
        SPA (see bizal/dashboard.py and the per-app admin.py registrations)
        and is now the single platform-superadmin surface. It must only be
        reachable on the main domain — request.tenant is None there, and a
        real Tenant object on any subdomain. Without this check, a tenant
        business owner hitting hertz.bizal.al/django-admin/ would land on
        Django's own login screen for a surface that controls every tenant
        on the platform, not just theirs.
        Raising Http404 here (rather than redirecting) deliberately gives
        no signal that the path exists at all on a tenant subdomain.
        """
        if request.tenant is not None and request.path.startswith('/django-admin'):
            raise Http404('Not found.')

    def _enforce_trial(self, request):
        """
        If the tenant is on a trial that has expired, mark is_active=False.
        Runs at most once per 5 min (cached) so we don't hit the DB on
        every single request.

        IMPORTANT: we deliberately do NOT raise Http404 here. A 404 sends
        the visitor to a generic "not found" page with no way forward.
        Instead we let the request through; the frontend reads
        `trial_expired` (and `is_active`) from GET /api/tenants/info/ and
        renders a proper "your trial has expired — upgrade to continue"
        screen. We intentionally do NOT downgrade `plan` to 'starter'
        either, so the `trial_expired` property (which only reports True
        while plan == 'trial') keeps working after deactivation.
        """
        tenant = request.tenant
        if tenant is None:
            return
        if tenant.plan != PLAN_TRIAL:
            return
        if not tenant.trial_ends_at:
            return
        if timezone.now() <= tenant.trial_ends_at:
            return

        # Trial expired — downgrade once, then cache so we don't hit DB every request.
        # MED-5 FIX: TTL reduced from 300s to 60s. The webhook handlers for
        # checkout.session.completed and customer.subscription.updated already call
        # cache.delete('trial_expired:{slug}') to invalidate this immediately on payment,
        # so the 60s window only matters for the rare race where the webhook fires
        # between the cache.set() here and the delete() in the webhook handler.
        cache_key = f'trial_expired:{tenant.slug}'
        if not cache.get(cache_key):
            # MED-1 FIX: wrap the is_active=True check and UPDATE in an atomic
            # block so concurrent requests to an expiring-trial tenant can't both
            # read is_active=True and both issue the UPDATE, risking a stale
            # cache being set after the delete (TOCTOU race). Using
            # filter(is_active=True) as the WHERE clause makes the UPDATE a
            # conditional no-op on the second concurrent request.
            if tenant.is_active:
                with transaction.atomic():
                    updated = Tenant.objects.filter(pk=tenant.pk, is_active=True).update(is_active=False)
                    if updated:
                        cache.delete(f'tenant:{tenant.slug}')
            # M-1 FIX: Always set the trial_expired cache key on a cache miss,
            # regardless of whether is_active was True or False. Without this,
            # already-inactive tenants never get the cache key set, so the 60s
            # guard never fires and every cache miss triggers a full middleware
            # check under continuous traffic to an expired-trial tenant.
            cache.set(cache_key, True, 60)

        # Reflect the deactivation on the in-memory object for this request
        # so anything downstream that checks request.tenant.is_active sees
        # the up-to-date value without another DB hit.
        tenant.is_active = False

    def _resolve_tenant(self, request):
        host_header = request.get_host().lower()

        # L-2 FIX: reference the module-level _BYPASS_SET (computed once at
        # import time) instead of rebuilding the set on every request.
        # CRIT-1 FIX: use exact path match, not endswith(), to prevent path-
        # traversal bypass (e.g. /malicious/api/payments/webhook would
        # incorrectly pass the old endswith() check).
        # CRIT-1 FIX: Bypass paths must be checked BEFORE any port/subdomain
        # dispatch. Without this early return, /health/ on port 8001 hits the
        # TENANT_PORT branch which raises Http404 when no ?tenant= is present,
        # causing the spa healthcheck to always fail -> container never healthy
        # -> nginx never starts (docker-compose depends_on service_healthy).
        if request.path.rstrip('/') in _BYPASS_SET:
            return None

        # After the early return above, we know this path is NOT a bypass path.
        # All production subdomain lookups therefore use strict=True (no fallback
        # to a default tenant). The strict=False path is only used for the explicit
        # local-dev port-8001 branch below, where it is hard-coded directly.
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
            return None

        if host.endswith(f'.{MAIN_DOMAIN}'):
            slug = host[:-(len(MAIN_DOMAIN) + 1)]
            # FIX #1: Strip leading 'www.' from slug in case someone visits
            # www.hertz.bizal.al — treat it as hertz.bizal.al, not as slug='www.hertz'.
            if slug.startswith('www.'):
                slug = slug[4:]
            return self._get_tenant(slug, strict=True)

        # ── LOCAL DEV ────────────────────────────────────────────
        if host.endswith(f'.{LOCAL_DOMAIN}'):
            slug = host[:-(len(LOCAL_DOMAIN) + 1)]
            # FIX #1: Strip www. prefix; skip blank/www slugs entirely.
            if slug.startswith('www.'):
                slug = slug[4:]
            if slug and slug not in ('www', ''):
                return self._get_tenant(slug, strict=True)

        is_main_local = host in (LOCAL_DOMAIN, '127.0.0.1', '0.0.0.0')

        if is_main_local:
            if port == MAIN_PORT:
                return None

            if port == TENANT_PORT:
                slug = request.GET.get('tenant', '').strip()
                if slug:
                    request.session[SESSION_KEY] = slug
                    request.session.modified = True
                else:
                    slug = request.session.get(SESSION_KEY, '').strip()

                if not slug:
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
        if not slug:
            return None

        cache_key = f'tenant:{slug}'
        tenant = cache.get(cache_key)

        if tenant is None:
            try:
                tenant = Tenant.objects.prefetch_related('features', 'locations').get(slug=slug)
                if tenant.is_active:
                    cache.set(cache_key, tenant, 300)
                else:
                    # Cache inactive tenants briefly (60s) so a pending,
                    # suspended, or trial-expired tenant doesn't cause a DB
                    # hit on every single request. 60s is short enough that
                    # a superadmin activation is reflected quickly, but long
                    # enough to protect the DB under traffic.
                    cache.set(cache_key, tenant, 60)
            except Tenant.DoesNotExist:
                raise Http404(f'No tenant found for slug: "{slug}"')

        if strict and not tenant.is_active:
            # Trial-expired tenants are deliberately let through rather than
            # 404'd — the SPA reads `trial_expired`/`is_active` from
            # /api/tenants/info/ and shows an upgrade screen. Anyone else
            # who's inactive (pending activation, suspended, etc.) still
            # gets the 404.
            if tenant.plan == PLAN_TRIAL and tenant.trial_expired:
                return tenant
            raise Http404(
                f'Tenant "{slug}" is not yet active. '
                f'Contact support or wait for activation.'
            )

        return tenant
