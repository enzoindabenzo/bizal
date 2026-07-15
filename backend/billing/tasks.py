"""
Celery tasks for billing.

To run periodically, register them in CELERY_BEAT_SCHEDULE in settings/base.py.
"""
from django.utils import timezone
# HIGH-1 FIX: Import from django.db.utils, not psycopg2 directly.
# Django wraps driver-level exceptions and re-raises them as
# django.db.utils.OperationalError (a subclass of django.db.OperationalError).
# psycopg2.OperationalError and django.db.utils.OperationalError are different
# classes — autoretry_for=(psycopg2.OperationalError, ...) would never match
# a Django-ORM-raised exception, silently disabling the retry logic entirely.
from django.db.utils import OperationalError
from celery import shared_task


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=300,  # 5 minutes
    # M-3 FIX: Narrowed from (OperationalError, DatabaseError) to only OperationalError.
    # DatabaseError is the base class for ALL Django DB exceptions, including
    # ProgrammingError (bad SQL / missing column from unapplied migration) and
    # IntegrityError (constraint violation). These are programming errors — not
    # transient failures — and retrying them up to 3× with hour-long backoff buries
    # the real problem and clogs the Celery queue. OperationalError covers the
    # genuinely transient cases: connection refused, server closed connection, deadlock.
    autoretry_for=(OperationalError,),
    retry_backoff=True,
    retry_backoff_max=3600,  # cap at 1 hour
)
def mark_overdue_invoices(self):
    # FIX: Added retry logic — if the DB is temporarily unavailable
    # (e.g. during a failover), the task retries with exponential backoff
    # instead of silently failing and skipping invoices for the day.
    """Mark all sent invoices past their due_date as overdue."""
    from .models import Invoice
    today = timezone.localdate()  # Honours TIME_ZONE (Europe/Tirane) regardless of system clock or TZ env var.
    updated = Invoice.objects.filter(
        status='sent',
        due_date__lt=today,
    ).update(status='overdue')
    return f"Marked {updated} invoice(s) as overdue."
