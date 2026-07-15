from django.db import models
from bizal.base_models import TenantScopedUUIDModel

ROLE_CHOICES = [
    ('manager', 'Manager'),
    ('receptionist', 'Receptionist'),
    ('accountant', 'Accountant'),
    ('staff', 'Staff'),
]

SCHEDULE_CHOICES = [
    ('monday', 'Monday'),
    ('tuesday', 'Tuesday'),
    ('wednesday', 'Wednesday'),
    ('thursday', 'Thursday'),
    ('friday', 'Friday'),
    ('saturday', 'Saturday'),
    ('sunday', 'Sunday'),
]


class StaffMember(TenantScopedUUIDModel):
    user = models.OneToOneField(
        'accounts.User', on_delete=models.CASCADE, related_name='staff_profile'
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='staff')
    position = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    hire_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['user__full_name']

    def __str__(self):
        return f"{self.user.display_name} ({self.role})"


class StaffSchedule(TenantScopedUUIDModel):
    staff = models.ForeignKey(StaffMember, on_delete=models.CASCADE, related_name='schedules')
    day = models.CharField(max_length=20, choices=SCHEDULE_CHOICES)
    start_time = models.TimeField()
    end_time = models.TimeField()

    class Meta:
        unique_together = ('staff', 'day')
        ordering = ['day']

    def __str__(self):
        return f"{self.staff} — {self.day}"
