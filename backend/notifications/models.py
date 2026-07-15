from django.db import models
from bizal.base_models import TenantScopedUUIDModel

TYPE_CHOICES = [
    ('booking_confirmed', 'Booking Confirmed'),
    ('booking_cancelled', 'Booking Cancelled'),
    ('appointment_reminder', 'Appointment Reminder'),
    ('appointment_new', 'New Appointment'),
    ('order_placed', 'Order Placed'),
    ('payment_success', 'Payment Successful'),
    ('subscription_expiring', 'Subscription Expiring'),
    ('new_review', 'New Review'),
    ('new_contact', 'New Contact Message'),
    ('chatbot_handoff', 'Chatbot Handoff'),
    ('info', 'Info'),
]


class Notification(TenantScopedUUIDModel):
    user = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='notifications')
    notification_type = models.CharField(max_length=50, choices=TYPE_CHOICES)
    title = models.CharField(max_length=200)
    body = models.TextField()
    is_read = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict, blank=True)
    # M-3 FIX: optional dedup key. notify_owner() previously had no way to
    # guard against creating the same notification twice — e.g. a Celery
    # task retry after a transient DB error (notify_owner_async) would call
    # notify_owner() again with no idempotency guard, silently duplicating
    # every owner/manager's notification for that one real-world event.
    # Left blank ('') for the vast majority of call sites that have no
    # natural dedup key and should always insert (e.g. ad-hoc admin
    # notices); callers that DO have a stable source identifier (a booking
    # id, an order id, a retried task's args) can pass it through
    # MED-5 FIX: Increased from 120 to 200 to give headroom for composite keys
    # (e.g. 'appointment_reminder_{tenant_slug}_{appointment_id}'). At 120 chars
    # future callers with longer prefixes would silently truncate, potentially
    # colliding the uniqueness constraint or creating false no-ops.
    # Callers that DO have a stable source identifier (a booking id, an order id,
    # a retried task's args) pass it through to make repeated calls for the
    # same source a no-op instead of a duplicate row.
    idempotency_key = models.CharField(max_length=200, blank=True, default='')

    class Meta:
        ordering = ['-created_at']
        constraints = [
            # Only enforced when idempotency_key is set — blank keys are
            # exempt so every pre-existing caller that never passes one
            # keeps inserting freely, exactly as before.
            models.UniqueConstraint(
                fields=['tenant', 'user', 'notification_type', 'idempotency_key'],
                condition=~models.Q(idempotency_key=''),
                name='uniq_notification_idempotency_key',
            ),
        ]

    def __str__(self):
        return f"{self.user} - {self.notification_type}"
