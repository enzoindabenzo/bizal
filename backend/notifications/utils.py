"""
Notification helpers — call these from other apps to create in-app notifications.

Usage:
    from notifications.utils import notify_owner, notify_user

    # Notify the tenant owner about a new booking
    notify_owner(tenant, 'booking_confirmed', 'New Booking', f'{guest} booked {service}')

    # Same, but idempotent across retries of the same source event — a
    # second call with the same idempotency_key for this tenant/type is a
    # silent no-op instead of a duplicate notification per owner/manager.
    notify_owner(
        tenant, 'booking_confirmed', 'New Booking', f'{guest} booked {service}',
        idempotency_key=f'booking:{booking.id}',
    )

    # Notify a specific user
    notify_user(user, tenant, 'info', 'Welcome!', 'Thanks for joining.')
"""
from .models import Notification


def notify_owner(tenant, notification_type, title, body, metadata=None, idempotency_key=''):
    """Send a notification to all owner/manager users of a tenant.

    M-3 FIX: pass idempotency_key for any call that might run more than
    once for the same real-world event (most importantly,
    notifications.tasks.notify_owner_async, which Celery may retry after a
    transient DB error). bulk_create(..., ignore_conflicts=True) combined
    with the conditional unique constraint on
    (tenant, user, notification_type, idempotency_key) means a retried
    call with the same key silently skips rows that already exist instead
    of creating duplicates — while every call that leaves idempotency_key
    blank (the default, matching all pre-existing call sites) is
    unaffected and still always inserts.
    """
    from accounts.models import User
    owners = User.objects.filter(
        tenant=tenant,
        role__in=('owner', 'manager'),
        is_active=True,
    )
    notifications = [
        Notification(
            tenant=tenant,
            user=owner,
            notification_type=notification_type,
            title=title,
            body=body,
            metadata=metadata or {},
            idempotency_key=idempotency_key or '',
        )
        for owner in owners
    ]
    Notification.objects.bulk_create(notifications, ignore_conflicts=True)
    if not notifications:
        import logging as _log
        _log.getLogger(__name__).debug(
            'notify_owner: tenant %s has no active owner/manager — '
            'notification type=%s dropped',
            tenant.slug, notification_type,
        )


def notify_user(user, tenant, notification_type, title, body, metadata=None):
    """Send a notification to a single user."""
    if user and user.is_active:
        Notification.objects.create(
            tenant=tenant,
            user=user,
            notification_type=notification_type,
            title=title,
            body=body,
            metadata=metadata or {},
        )
