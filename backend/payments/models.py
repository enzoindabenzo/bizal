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
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='ALL')
    payment_type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    stripe_session_id = models.CharField(max_length=200, blank=True)
    stripe_payment_intent = models.CharField(max_length=200, blank=True)
    description = models.CharField(max_length=300, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.tenant} | {self.payment_type} | {self.amount} {self.currency}"
