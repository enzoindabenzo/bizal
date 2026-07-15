from django.db import models
from bizal.base_models import TenantScopedUUIDModel

FREQUENCY_CHOICES = [
    ('daily', 'Daily'),
    ('weekly', 'Weekly'),
    ('monthly', 'Monthly'),
    ('yearly', 'Yearly'),
]

STATUS_CHOICES = [
    ('active', 'Active'),
    ('paused', 'Paused'),
    ('cancelled', 'Cancelled'),
]


class CustomerSubscription(TenantScopedUUIDModel):
    """
    Recurring subscriptions a tenant sells to their own customers
    (e.g. a gym monthly pass, a meal kit weekly box, a barber monthly trim).
    These are distinct from the tenant's BizAL plan (handled in tenants/models.py).
    """
    customer = models.ForeignKey(
        'accounts.User', on_delete=models.CASCADE, related_name='customer_subscriptions'
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    frequency = models.CharField(max_length=20, choices=FREQUENCY_CHOICES, default='monthly')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    started_at = models.DateField(null=True, blank=True)
    next_billing_date = models.DateField(null=True, blank=True)
    stripe_subscription_id = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.customer} — {self.name} ({self.frequency})"
