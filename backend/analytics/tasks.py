"""
Celery tasks for the analytics app.
"""
from celery import shared_task
from django.utils import timezone
from datetime import timedelta


@shared_task
def purge_old_events(days=90, batch_size=25000):
    """
    Delete AnalyticsEvent rows older than `days` days (default: 90).

    MED-1 FIX: Previously deleted all matching rows in a single transaction,
    which on a large multi-tenant table could hold a table lock for minutes,
    blocking concurrent analytics writes. Now deletes in batches of `batch_size`
    with a brief yield between iterations to keep lock contention minimal.

    MEDIUM-2 FIX: The previous global ordering by (created_at, id) meant that
    on a system with one very active tenant all 25,000 rows in every batch may
    belong to that tenant, starving smaller tenants' old rows across MAX_BATCHES
    iterations. We now process each tenant in turn — each tenant gets at most
    `per_tenant_batch` deletes per task run, guaranteeing forward progress for
    every tenant regardless of volume distribution.

    A tenant generating 10k page views/day accumulates ~3.6M rows/year.
    Without purging, query times on the tenant+created_at index degrade and
    table bloat slows VACUUM. Running weekly at off-peak hours keeps the
    table to roughly 900k rows per active tenant.

    Scheduled in CELERY_BEAT_SCHEDULE (bizal/settings/base.py) to run
    every Sunday at 04:00 UTC.
    """
    import time
    from .models import AnalyticsEvent
    try:
        from tenants.models import Tenant
        tenant_ids = list(Tenant.objects.filter(is_active=True).values_list('id', flat=True))
    except Exception:
        tenant_ids = []

    cutoff = timezone.now() - timedelta(days=days)
    total = 0

    # Per-tenant cap: limit how many rows we purge per tenant per run so one
    # busy tenant cannot exhaust the entire task budget (MAX_BATCHES * batch_size).
    # Across all tenants, we still cap at MAX_BATCHES total iterations.
    MAX_BATCHES = 10_000
    batches_used = 0

    if tenant_ids:
        per_tenant_batches = max(1, MAX_BATCHES // len(tenant_ids))
        for tenant_id in tenant_ids:
            # MEDIUM-1 FIX: break the outer loop too when the batch budget is
            # exhausted — previously only the inner loop broke, so all remaining
            # tenant IDs were iterated with no work performed (wasted loop overhead).
            if batches_used >= MAX_BATCHES:
                break
            for _ in range(per_tenant_batches):
                if batches_used >= MAX_BATCHES:
                    break
                ids = list(
                    AnalyticsEvent.objects.filter(
                        tenant_id=tenant_id, created_at__lt=cutoff
                    )
                    .order_by('created_at', 'id')
                    .values_list('id', flat=True)[:batch_size]
                )
                if not ids:
                    break
                deleted, _ = AnalyticsEvent.objects.filter(id__in=ids).delete()
                total += deleted
                batches_used += 1
                if deleted < batch_size:
                    break
                time.sleep(0.1)
    else:
        # Fallback: no tenant list available — fall back to global ordering
        for _ in range(MAX_BATCHES):
            ids = list(
                AnalyticsEvent.objects.filter(created_at__lt=cutoff)
                .order_by('created_at', 'id')
                .values_list('id', flat=True)[:batch_size]
            )
            if not ids:
                break
            deleted, _ = AnalyticsEvent.objects.filter(id__in=ids).delete()
            total += deleted
            if deleted < batch_size:
                break
            time.sleep(0.1)

    return f"Purged {total} AnalyticsEvent rows older than {days} days."
