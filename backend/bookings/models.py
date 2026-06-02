from django.db import models
from bizal.base_models import TenantScopedUUIDModel

STATUS_CHOICES = [
    ('pending', 'Pending'),
    ('confirmed', 'Confirmed'),
    ('active', 'Active'),
    ('completed', 'Completed'),
    ('cancelled', 'Cancelled'),
    ('no_show', 'No Show'),
]

BOOKING_TYPE_CHOICES = [
    ('table_reservation', 'Table Reservation'),
    ('room_booking', 'Room Booking'),
    ('rental', 'Rental'),
    ('appointment', 'Appointment'),
    ('class', 'Class'),
    ('event', 'Event'),
    ('delivery', 'Delivery Order'),
]


class Booking(TenantScopedUUIDModel):
    user = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, related_name='bookings'
    )
    booking_type = models.CharField(max_length=30, choices=BOOKING_TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')

    # Date/time
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)

    # Generic FK: can point to a room, car, service slot, table, etc.
    resource_type = models.CharField(max_length=100, blank=True)
    resource_id = models.PositiveIntegerField(null=True, blank=True)
    resource_label = models.CharField(max_length=200, blank=True)

    # Guest info (for non-registered users)
    guest_name = models.CharField(max_length=200, blank=True)
    guest_email = models.EmailField(blank=True)
    guest_phone = models.CharField(max_length=30, blank=True)
    guest_count = models.PositiveSmallIntegerField(default=1)

    # Financials
    total_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    deposit_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    stripe_session_id = models.CharField(max_length=200, blank=True)

    notes = models.TextField(blank=True)
    internal_notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.booking_type} @ {self.tenant} [{self.status}]"
