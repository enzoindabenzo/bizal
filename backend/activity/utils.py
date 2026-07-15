"""
Small helper other apps call to write an activity log entry.

Usage:
    from activity.utils import log_activity

    log_activity(
        tenant=booking.tenant,
        actor=request.user,
        verb='booking.confirmed',
        description=f'Confirmed booking for {booking.guest_name}',
        target_type='booking',
        target_id=booking.id,
    )

Logging is best-effort: a failure to write an activity entry should never
break the request that triggered it.
"""
import logging

logger = logging.getLogger(__name__)


def log_activity(tenant, actor, verb, description, target_type='', target_id='', metadata=None):
    if tenant is None:
        return None

    from .models import ActivityLog

    actor_name = ''
    actor_obj = None
    if actor is not None and getattr(actor, 'is_authenticated', False):
        actor_obj = actor
        actor_name = actor.display_name if hasattr(actor, 'display_name') else str(actor)

    try:
        return ActivityLog.objects.create(
            tenant=tenant,
            actor=actor_obj,
            actor_name=actor_name,
            verb=verb,
            description=description,
            target_type=target_type,
            target_id=str(target_id) if target_id else '',
            metadata=metadata or {},
        )
    except Exception:
        logger.exception('Failed to write activity log entry: %s', description)
        return None
