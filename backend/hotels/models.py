from django.db import models
from bizal.base_models import TenantScopedUUIDModel

ROOM_STATUS = [
    ('available', 'Available'),
    ('occupied', 'Occupied'),
    ('maintenance', 'Maintenance'),
    ('reserved', 'Reserved'),
]


class RoomType(TenantScopedUUIDModel):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    capacity = models.PositiveSmallIntegerField(default=2)
    base_price = models.DecimalField(max_digits=8, decimal_places=2)
    image = models.ImageField(upload_to='hotels/rooms/', blank=True, null=True)
    amenities = models.JSONField(default=list, blank=True)

    def __str__(self):
        return self.name


class Room(TenantScopedUUIDModel):
    room_type = models.ForeignKey(RoomType, on_delete=models.CASCADE, related_name='rooms')
    room_number = models.CharField(max_length=20)
    floor = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(max_length=20, choices=ROOM_STATUS, default='available')
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['floor', 'room_number']

    def __str__(self):
        return f"Room {self.room_number} ({self.room_type.name})"


class SeasonalPrice(TenantScopedUUIDModel):
    room_type = models.ForeignKey(RoomType, on_delete=models.CASCADE, related_name='seasonal_prices')
    name = models.CharField(max_length=100)
    start_date = models.DateField()
    end_date = models.DateField()
    price = models.DecimalField(max_digits=8, decimal_places=2)

    def __str__(self):
        return f"{self.name}: {self.start_date} - {self.end_date}"
