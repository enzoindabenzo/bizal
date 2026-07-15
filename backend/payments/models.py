from django.db import models
from bizal.base_models import TenantScopedUUIDModel

STATUS_CHOICES = [
    ('pending', 'Pending'),
    ('completed', 'Completed'),
    ('failed', 'Failed'),
    ('refunded', 'Refunded'),
]

TYPE_CHOICES = [
    ('subscription', 'Subscription'),
    ('booking_deposit', 'Booking Deposit'),
    ('order', 'Order'),
    ('invoice', 'Invoice'),
]


class Payment(TenantScopedUUIDModel):
    user = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, related_name='payments')
    # Only set for payment_type='booking_deposit' rows. Nullable/SET_NULL so
    # deleting a Booking (not currently possible via the API, but defensively)
    # doesn't cascade-delete its billing history.
    booking = models.ForeignKey(
        'bookings.Booking', on_delete=models.SET_NULL, null=True, blank=True, related_name='payments'
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='ALL')
    payment_type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    stripe_session_id = models.CharField(max_length=200, blank=True, db_index=True)
    stripe_payment_intent = models.CharField(max_length=200, blank=True)
    description = models.CharField(max_length=300, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            # Prevent duplicate Payment rows from concurrent Stripe webhook
            # retries. Partial: empty stripe_session_id is allowed (e.g.
            # subscription.deleted events which carry no session ID).
            models.UniqueConstraint(
                fields=['stripe_session_id'],
                condition=~models.Q(stripe_session_id=''),
                name='unique_stripe_session_id',
            ),
            # L-2 FIX: Guard against duplicate Payment rows for invoice.payment_failed
            # events when the Redis idempotency cache is evicted between concurrent
            # Stripe retries. Partial: empty stripe_payment_intent is allowed.
            models.UniqueConstraint(
                fields=['tenant', 'stripe_payment_intent'],
                condition=~models.Q(stripe_payment_intent=''),
                name='unique_tenant_payment_intent',
            ),
        ]

    def __str__(self):
        return f"{self.tenant} | {self.payment_type} | {self.amount} {self.currency}"


class WebhookEvent(models.Model):
    """
    Audit log of every incoming Stripe webhook event.
    Allows superadmin to inspect webhook history and debug billing issues
    without grepping server logs.
    """
    stripe_event_id = models.CharField(max_length=200, unique=True, db_index=True)
    event_type      = models.CharField(max_length=100, db_index=True)
    status          = models.CharField(
        max_length=20,
        choices=[('processed', 'Processed'), ('ignored', 'Ignored'), ('failed', 'Failed')],
        default='processed',
    )
    payload         = models.JSONField(default=dict, blank=True)
    error_message   = models.TextField(blank=True)
    created_at      = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        # stripe_event_id already has unique=True — no extra constraint needed.

    def __str__(self):
        return f"{self.event_type} [{self.status}]"
