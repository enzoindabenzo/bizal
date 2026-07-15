from django.db import models
from bizal.base_models import TenantScopedUUIDModel
from bizal.validators import validate_image_type

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
    image = models.ImageField(upload_to='hotels/rooms/', blank=True, null=True, validators=[validate_image_type])
    amenities = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ['name']

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

    class Meta:
        ordering = ['start_date']

    def __str__(self):
        return f"{self.name}: {self.start_date} - {self.end_date}"


class RoomBooking(models.Model):
    """
    Thin join table used purely for overlap detection on hotel room bookings.

    When a booking is created for booking_type='room_booking', a RoomBooking
    row is written linking the generic Booking to a specific Room. The
    is_available_for() method queries this table — mirroring the pattern
    already used by RentalItem — so two bookings for the same room on
    overlapping dates are rejected.

    This model intentionally does NOT duplicate booking data (dates, prices).
    It only exists for the overlap index; all user-facing data lives on
    Booking itself.
    """
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='room_bookings')
    booking = models.OneToOneField(
        'bookings.Booking', on_delete=models.CASCADE, related_name='room_booking'
    )

    class Meta:
        indexes = [
            models.Index(fields=['room', 'booking']),
        ]

    def __str__(self):
        return f"Room {self.room.room_number} → Booking {self.booking_id}"


def is_room_available(room, start_date, end_date, exclude_booking_id=None):
    """
    Return True if the given Room is in 'available' status AND has no
    confirmed/active bookings that overlap [start_date, end_date).

    MEDIUM FIX: Previously this function only checked for booking row overlaps
    and never inspected room.status. A room manually set to 'maintenance',
    'occupied', or 'reserved' by tenant staff could still be booked through
    the API because the overlap query returned no rows for non-overlapping
    dates regardless of the room's status flag. This mirrors the existing
    behaviour in RentalItem.is_available_for() (rentals/models.py:53) which
    correctly gates on self.status == 'available' in addition to the overlap
    check.

    Overlap condition (Allen's interval algebra):
        existing.start < requested.end  AND  existing.end > requested.start

    MUST be called inside a transaction.atomic() block with select_for_update()
    on the Room row so that concurrent requests cannot both observe "available"
    before either INSERT commits (TOCTOU race / double-booking).

    Usage (in a view or serializer that already holds the lock):
        with transaction.atomic():
            room = Room.objects.select_for_update().get(pk=room_id, tenant=tenant)
            if not is_room_available(room, check_in, check_out):
                raise serializers.ValidationError('Room not available for these dates.')
            booking = Booking.objects.create(...)
    """
    # Gate on the room's own status first — no overlap query needed if the
    # room is not in a bookable state (maintenance, occupied, reserved).
    if room.status != 'available':
        return False

    from bookings.models import Booking
    qs = Booking.objects.filter(
        room_booking__room=room,
        # Include 'pending' to block overlaps for bookings not yet confirmed.
        # Without 'pending', two customers can book the same room simultaneously
        # since neither's booking appears confirmed during the overlap check.
        # Mirrors the fix in rentals/models.py and appointments/serializers.py.
        status__in=('pending', 'confirmed', 'active'),
        start_date__lt=end_date,
        end_date__gt=start_date,
    )
    if exclude_booking_id:
        qs = qs.exclude(pk=exclude_booking_id)
    return not qs.exists()
