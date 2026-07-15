"""
Call track() from any app to record an analytics event for a tenant.

Usage:
    from analytics.utils import track
    track(request, tenant, 'page_view', page='/services/')
    track(request, tenant, 'booking_created', metadata={'service': 'Haircut'})
"""
import hashlib
import logging

from .models import AnalyticsEvent

logger = logging.getLogger(__name__)


def track(request, tenant, event_type, page='', metadata=None):
    """
    Create an AnalyticsEvent. Silently swallows exceptions so it never
    breaks callers.

    FIX #5: Guard against tenant=None (main-domain requests). Recording
    events without a tenant creates corrupt DB rows that pollute every
    aggregate query. Callers already pass the tenant explicitly, so this
    is a no-op for legitimate calls but prevents accidental main-domain leakage.
    """
    # Tenant guard — never write analytics without a tenant
    if tenant is None:
        return
    # CRIT-2 FIX: Only write analytics events when the tenant's plan includes
    # the analytics feature. Starter and other non-analytics plans were
    # silently accumulating AnalyticsEvent rows that could never be read
    # (the dashboard correctly gates on has_feature('analytics')), causing
    # DB bloat at scale (100k+ wasted writes/day on a modest install).
    if not tenant.has_feature('analytics'):
        return

    try:
        # Use the IP address nginx forwards verbatim as X-Real-IP ($remote_addr),
        # which cannot be spoofed by clients. Taking the first element of
        # X-Forwarded-For is wrong here because nginx *appends* the real client
        # IP to the end of that header — a client-supplied prefix is picked up
        # instead, allowing trivial spoofing. X-Real-IP is set to $remote_addr
        # by nginx unconditionally, matching the pattern used correctly in
        # contact/views.py and blog/views.py.
        ip = (
            request.META.get('HTTP_X_REAL_IP', '').strip()
            or request.META.get('REMOTE_ADDR', '')
        )
        ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:32] if ip else ''
        AnalyticsEvent.objects.create(
            tenant=tenant,
            event_type=event_type,
            page=page or request.path,
            referrer=request.META.get('HTTP_REFERER', '')[:500],
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
            ip_hash=ip_hash,
            metadata=metadata or {},
        )
    except Exception:
        logger.debug('analytics.track silenced exception', exc_info=True)
