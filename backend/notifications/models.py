from django.db import models
from bizal.base_models import TenantScopedUUIDModel

TYPE_CHOICES = [
    ('booking_confirmed', 'Booking Confirmed'),
    ('booking_cancelled', 'Booking Cancelled'),
    ('appointment_reminder', 'Appointment Reminder'),
    ('payment_success', 'Payment Successful'),
    ('subscription_expiring', 'Subscription Expiring'),
    ('new_review', 'New Review'),
    ('new_contact', 'New Contact Message'),
    ('info', 'Info'),
]


class Notification(TenantScopedUUIDModel):
    user = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='notifications')
    notification_type = models.CharField(max_length=50, choices=TYPE_CHOICES)
    title = models.CharField(max_length=200)
    body = models.TextField()
    is_read = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user} - {self.notification_type}"
