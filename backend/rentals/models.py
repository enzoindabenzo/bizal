from django.db import models
from bizal.base_models import TenantScopedUUIDModel

RENTAL_TYPE_CHOICES = [
    ('car', 'Car'),
    ('property', 'Property'),
    ('equipment', 'Equipment'),
    ('boat', 'Boat'),
]

STATUS_CHOICES = [
    ('available', 'Available'),
    ('rented', 'Rented'),
    ('maintenance', 'Maintenance'),
    ('unavailable', 'Unavailable'),
]


class RentalItem(TenantScopedUUIDModel):
    name = models.CharField(max_length=200)
    rental_type = models.CharField(max_length=30, choices=RENTAL_TYPE_CHOICES)
    description = models.TextField(blank=True)
    price_per_day = models.DecimalField(max_digits=8, decimal_places=2)
    deposit = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='available')
    image = models.ImageField(upload_to='rentals/', blank=True, null=True)
    city = models.CharField(max_length=100, blank=True)
    specs = models.JSONField(default=dict, blank=True)  # flexible: seats, year, fuel, etc.
    is_featured = models.BooleanField(default=False)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.rental_type})"

    def is_available_for(self, start_date, end_date):
        from bookings.models import Booking
        overlapping = Booking.objects.filter(
            tenant=self.tenant,
            resource_id=self.pk,
            resource_type='rental_item',
            status__in=('confirmed', 'active'),
            start_date__lt=end_date,
            end_date__gt=start_date,
        ).exists()
        return not overlapping and self.status == 'available'
