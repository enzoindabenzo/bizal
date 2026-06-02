from django.db import models
from bizal.base_models import TenantScopedUUIDModel

STATUS_CHOICES = [
    ('pending', 'Pending'),
    ('confirmed', 'Confirmed'),
    ('completed', 'Completed'),
    ('cancelled', 'Cancelled'),
    ('no_show', 'No Show'),
]


class ServiceProvider(TenantScopedUUIDModel):
    """Doctor, barber, trainer, lawyer, etc."""
    name = models.CharField(max_length=200)
    title = models.CharField(max_length=100, blank=True)
    bio = models.TextField(blank=True)
    avatar = models.ImageField(upload_to='providers/', blank=True, null=True)
    is_active = models.BooleanField(default=True)
    specialties = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.title} {self.name}".strip()


class Service(TenantScopedUUIDModel):
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    duration_minutes = models.PositiveSmallIntegerField(default=60)
    price = models.DecimalField(max_digits=8, decimal_places=2)
    providers = models.ManyToManyField(ServiceProvider, blank=True, related_name='services')
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Appointment(TenantScopedUUIDModel):
    user = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True)
    provider = models.ForeignKey(ServiceProvider, on_delete=models.SET_NULL, null=True, blank=True)
    service = models.ForeignKey(Service, on_delete=models.SET_NULL, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')

    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()

    guest_name = models.CharField(max_length=200, blank=True)
    guest_email = models.EmailField(blank=True)
    guest_phone = models.CharField(max_length=30, blank=True)

    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-date', '-start_time']

    def __str__(self):
        return f"{self.service} w/ {self.provider} on {self.date}"
