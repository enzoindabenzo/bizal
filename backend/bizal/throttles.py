from rest_framework.throttling import AnonRateThrottle, ScopedRateThrottle


class _FixedScopeThrottle(ScopedRateThrottle):
    """
    BUG FIX: DRF's ScopedRateThrottle.allow_request() does this as its
    first line:

        self.scope = getattr(view, self.scope_attr, None)   # scope_attr == 'throttle_scope'
        if not self.scope:
            return True   # <-- "always allow" fallback

    That reads the scope from a `throttle_scope` attribute on the VIEW,
    completely ignoring whatever `scope = '...'` is set on the throttle
    subclass itself. None of the views in this codebase set
    `throttle_scope`, so every plain ScopedRateThrottle subclass
    (PublicReadThrottle, TenantAdminThrottle) was silently hitting that
    "always allow" branch on every request — the configured rate had zero
    effect. Confirmed empirically: with the rate temporarily set to
    '2/day', 10 consecutive requests all still returned 200.

    Fix: don't depend on the view at all. Force `self.scope` back to this
    class's own `scope` attribute, then delegate to the grandparent
    (SimpleRateThrottle.allow_request) directly — bypassing
    ScopedRateThrottle's own allow_request (and its view-attribute lookup)
    while still reusing ScopedRateThrottle.get_cache_key via normal method
    resolution, so the per-user/per-IP + scope cache key still works.

    Every throttle below inherits from this instead of ScopedRateThrottle
    directly, so a future throttle class added the same way this file's
    existing ones were doesn't silently repeat the bug.
    """
    def allow_request(self, request, view):
        self.scope = self.__class__.scope
        self.rate = self.get_rate()
        self.num_requests, self.duration = self.parse_rate(self.rate)
        return super(ScopedRateThrottle, self).allow_request(request, view)


class PublicReadThrottle(_FixedScopeThrottle):
    """
    High-rate throttle for anonymous, render-blocking storefront reads
    (tenant info, reviews, storefront pages, service/menu/fleet listings).

    A single tenant page load fires several of these calls at once, so they
    must not share the tight 'anon' budget used by sensitive write endpoints
    — otherwise a handful of page refreshes locks every visitor out of the
    storefront (stuck on the loading skeleton) for the rest of the hour.
    """
    scope = 'public_read'


class AnonSensitiveThrottle(AnonRateThrottle):
    """
    Stricter throttle for anonymous endpoints that are genuinely abuse-prone:
    auth (login/register/password reset), contact forms, order/booking
    submission. Kept tight on purpose — this is the rate limit that should
    actually trigger on scripted abuse, not on normal browsing.

    NOTE: as of this writing, nothing in the codebase actually applies this
    throttle class to a view — the auth/registration/password-reset views
    use a separate django-ratelimit decorator (bizal.ratelimit_utils) instead,
    which does work correctly. This class is unused. Not touched here since
    fixing it isn't part of the bug being fixed, but flagging it because the
    settings.py comment above the 'anon_sensitive' rate claims sensitive
    endpoints "opt into the stricter anon_sensitive scope explicitly via
    throttle_classes", which isn't what actually happens in the current code.
    """
    scope = 'anon_sensitive'


class TenantAdminThrottle(_FixedScopeThrottle):
    """
    High-rate throttle for authenticated tenant-owner/staff admin write
    endpoints (storefront page/hero-slide management, etc). These already
    require IsTenantOwner/IsTenantStaff, so the throttle here exists only to
    blunt a genuinely runaway script — not to gate legitimate access. Sharing
    the default 'user' scope (1000/hour) with every other authenticated
    endpoint meant heavy admin tooling use (bulk imports, scripted content
    updates) could get throttled alongside normal customer-facing API calls.
    """
    scope = 'admin_write'
