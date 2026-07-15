from rest_framework import generics, status as drf_status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.exceptions import PermissionDenied
from django.db import transaction
from tenants.permissions import IsTenantOwner, HasTenantFeature
from tenants.limits import enforce_max_listings
from .models import RoomType, Room, SeasonalPrice, is_room_available
from .serializers import SeasonalPriceSerializer, RoomTypeSerializer, RoomSerializer

# Hotels are booking-heavy: RoomType/Room/SeasonalPrice management and the
# booking endpoints all require the tenant's plan to include 'bookings'.
BOOKINGS_FEATURE = HasTenantFeature('bookings')


class RoomTypeListView(generics.ListAPIView):
    serializer_class = RoomTypeSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        return RoomType.objects.filter(tenant=self.request.tenant).prefetch_related('seasonal_prices')


class RoomListView(generics.ListAPIView):
    serializer_class = RoomSerializer
    permission_classes = [IsTenantOwner]

    def get_queryset(self):
        return Room.objects.filter(tenant=self.request.tenant).select_related('room_type')


class RoomTypeCreateUpdateView(generics.CreateAPIView):
    serializer_class = RoomTypeSerializer
    permission_classes = [IsTenantOwner, BOOKINGS_FEATURE]

    def perform_create(self, serializer):
        with transaction.atomic():
            enforce_max_listings(self.request.tenant, RoomType)
            serializer.save(tenant=self.request.tenant)


class RoomTypeDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = RoomTypeSerializer

    def get_permissions(self):
        if self.request.method == 'GET':
            return [AllowAny()]
        return [IsTenantOwner(), BOOKINGS_FEATURE()]

    def get_queryset(self):
        return RoomType.objects.filter(tenant=self.request.tenant).prefetch_related('seasonal_prices')


class RoomsByTypeView(generics.ListCreateAPIView):
    """List rooms for a room type (public) or create a new one (owner only)."""
    serializer_class = RoomSerializer

    def get_permissions(self):
        if self.request.method == 'GET':
            return [AllowAny()]
        return [IsTenantOwner(), BOOKINGS_FEATURE()]

    def get_queryset(self):
        return Room.objects.filter(
            tenant=self.request.tenant, room_type_id=self.kwargs['pk'],
        ).select_related('room_type')

    def perform_create(self, serializer):
        with transaction.atomic():
            enforce_max_listings(self.request.tenant, Room)
            try:
                room_type = RoomType.objects.get(pk=self.kwargs['pk'], tenant=self.request.tenant)
            except RoomType.DoesNotExist:
                raise PermissionDenied('Room type not found for this tenant.')
            serializer.save(tenant=self.request.tenant, room_type=room_type)


class RoomDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update, or delete a single Room (owner only for write)."""
    serializer_class = RoomSerializer

    def get_permissions(self):
        if self.request.method == 'GET':
            return [AllowAny()]
        return [IsTenantOwner(), BOOKINGS_FEATURE()]

    def get_queryset(self):
        return Room.objects.filter(tenant=self.request.tenant).select_related('room_type')


class SeasonalPriceView(generics.ListCreateAPIView):
    serializer_class = SeasonalPriceSerializer
    permission_classes = [IsTenantOwner, BOOKINGS_FEATURE]

    def get_queryset(self):
        return SeasonalPrice.objects.filter(
            tenant=self.request.tenant,
            room_type_id=self.kwargs['pk'],
        )

    def perform_create(self, serializer):
        # IDOR fix: verify the RoomType identified by the URL kwarg belongs to
        # this tenant before creating a SeasonalPrice against it. Without this
        # check, a tenant owner could POST to /api/hotels/room-types/<foreign_uuid>/prices/
        # and create a price row linked to another tenant's room type.
        try:
            room_type = RoomType.objects.get(pk=self.kwargs['pk'], tenant=self.request.tenant)
        except RoomType.DoesNotExist:
            raise PermissionDenied('Room type not found for this tenant.')
        serializer.save(tenant=self.request.tenant, room_type=room_type)


# ── RoomBooking endpoints ──────────────────────────────────────────────────────

from rest_framework import serializers as drf_serializers
from .models import RoomBooking


class RoomBookingSerializer(drf_serializers.ModelSerializer):
    room_number    = drf_serializers.CharField(source='room.room_number', read_only=True)
    room_type_name = drf_serializers.CharField(source='room.room_type.name', read_only=True)
    booking_id     = drf_serializers.UUIDField(source='booking.id', read_only=True)
    guest_name     = drf_serializers.CharField(source='booking.guest_name', read_only=True)
    guest_email    = drf_serializers.EmailField(source='booking.guest_email', read_only=True)
    start_date     = drf_serializers.DateField(source='booking.start_date', read_only=True)
    end_date       = drf_serializers.DateField(source='booking.end_date', read_only=True)
    status         = drf_serializers.CharField(source='booking.status', read_only=True)
    total_price    = drf_serializers.DecimalField(source='booking.total_price', max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model  = RoomBooking
        fields = (
            'id', 'booking_id', 'room_number', 'room_type_name',
            'guest_name', 'guest_email', 'start_date', 'end_date',
            'status', 'total_price',
        )


class RoomBookingCreateSerializer(drf_serializers.Serializer):
    room_id     = drf_serializers.UUIDField()
    start_date  = drf_serializers.DateField()
    end_date    = drf_serializers.DateField()
    guest_name  = drf_serializers.CharField(max_length=200)
    guest_email = drf_serializers.EmailField()
    guest_phone = drf_serializers.CharField(max_length=30, required=False, allow_blank=True)
    guest_count = drf_serializers.IntegerField(min_value=1, default=1)
    notes       = drf_serializers.CharField(required=False, allow_blank=True)

    def validate(self, data):
        if data['end_date'] <= data['start_date']:
            raise drf_serializers.ValidationError('end_date must be after start_date.')
        return data


class RoomBookingListCreateView(generics.ListCreateAPIView):
    """
    GET  — list all room bookings for this tenant (owner only).
    POST — create a new room booking with overlap check (public).
    """
    def get_permissions(self):
        if self.request.method == 'GET':
            return [IsTenantOwner()]
        from rest_framework.permissions import AllowAny
        return [AllowAny()]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return RoomBookingCreateSerializer
        return RoomBookingSerializer

    def get_queryset(self):
        return RoomBooking.objects.filter(
            room__tenant=self.request.tenant,
        ).select_related('room__room_type', 'booking')

    def create(self, request, *args, **kwargs):
        # Guard: reject room bookings for tenants whose plan doesn't include
        # bookings. Mirrors the equivalent check in bookings/views.py's
        # BookingListCreateView.create() — this endpoint bypasses that
        # generic view and creates Booking objects directly, so it needs its
        # own copy of the same feature check.
        if not request.tenant:
            return Response(
                {'detail': 'Room bookings must be made from a tenant subdomain.'},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )
        if not request.tenant.has_feature('bookings'):
            return Response(
                {'detail': "Bookings are not available on this tenant's plan."},
                status=drf_status.HTTP_403_FORBIDDEN,
            )

        serializer = RoomBookingCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        from bookings.models import Booking

        with transaction.atomic():
            try:
                room = Room.objects.select_for_update().get(
                    pk=d['room_id'], tenant=request.tenant,
                )
            except Room.DoesNotExist:
                return Response(
                    {'detail': 'Room not found.'}, status=404
                )

            if not is_room_available(room, d['start_date'], d['end_date']):
                return Response(
                    {'detail': 'Room is not available for the selected dates.'},
                    status=409,
                )

            nights      = (d['end_date'] - d['start_date']).days
            total_price = room.room_type.base_price * nights

            booking = Booking.objects.create(
                tenant=request.tenant,
                user=request.user if request.user.is_authenticated else None,
                booking_type='room_booking',
                status='pending',
                start_date=d['start_date'],
                end_date=d['end_date'],
                guest_name=d['guest_name'],
                guest_email=d['guest_email'],
                guest_phone=d.get('guest_phone', ''),
                guest_count=d.get('guest_count', 1),
                notes=d.get('notes', ''),
                total_price=total_price,
                resource_label=f"Room {room.room_number} — {room.room_type.name}",
                resource_type='room',
                resource_id=str(room.pk),
            )
            rb = RoomBooking.objects.create(room=room, booking=booking)

        from notifications.tasks import send_booking_confirmation_email
        send_booking_confirmation_email.delay(str(booking.pk))

        return Response(RoomBookingSerializer(rb).data, status=201)


class RoomBookingDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class   = RoomBookingSerializer
    permission_classes = [IsTenantOwner]

    def get_queryset(self):
        return RoomBooking.objects.filter(
            room__tenant=self.request.tenant,
        ).select_related('room__room_type', 'booking')

    def perform_destroy(self, instance):
        instance.booking.status = 'cancelled'
        instance.booking.save(update_fields=['status', 'updated_at'])
        instance.delete()


@api_view(['GET'])
@permission_classes([AllowAny])
def find_available_room(request):
    """
    Given a room_type_id + start_date + end_date, returns the first concrete
    Room of that type that is available for the whole stay.

    The public storefront only ever lists RoomType objects (see
    RoomTypeListView) — never individual Room rows, since guests pick "a
    Deluxe Room", not "Room 204" specifically. But booking creation (both
    here and in bookings.BookingSerializer) needs an actual Room to run
    is_room_available()/select_for_update() against. This endpoint bridges
    that gap: it resolves room_type -> a specific available room, so the
    generic /api/bookings/ POST (and this app's own room-booking flow) can
    validate and price a stay without the client ever choosing/knowing a
    room number.

    NOTE: this performs a read-only lookup (no select_for_update, no
    transaction) purely to tell the client which room is currently free.
    The actual booking creation path takes the lock and re-validates
    availability at write time, so this endpoint cannot be used on its own
    to reserve anything and introduces no race condition.
    """
    room_type_id = request.query_params.get('room_type_id')
    start_date = request.query_params.get('start_date')
    end_date = request.query_params.get('end_date')
    if not (room_type_id and start_date and end_date):
        return Response(
            {'detail': 'room_type_id, start_date and end_date are required.'},
            status=drf_status.HTTP_400_BAD_REQUEST,
        )
    try:
        room_type = RoomType.objects.get(pk=room_type_id, tenant=request.tenant)
    except (RoomType.DoesNotExist, ValueError):
        return Response({'detail': 'Room type not found.'}, status=404)

    from datetime import date as _date
    try:
        sd = _date.fromisoformat(start_date)
        ed = _date.fromisoformat(end_date)
    except ValueError:
        return Response({'detail': 'Invalid date format, expected YYYY-MM-DD.'}, status=400)
    if ed <= sd:
        return Response({'detail': 'end_date must be after start_date.'}, status=400)

    candidate_rooms = Room.objects.filter(
        tenant=request.tenant, room_type=room_type, status='available',
    ).order_by('room_number')
    for room in candidate_rooms:
        if is_room_available(room, sd, ed):
            nights = (ed - sd).days
            return Response({
                'room_id': str(room.pk),
                'room_number': room.room_number,
                'room_type_id': str(room_type.pk),
                'nights': nights,
                'base_price': str(room_type.base_price),
                'total_price': str(room_type.base_price * nights),
            })
    return Response(
        {'detail': 'No rooms of this type are available for the selected dates.'},
        status=409,
    )


@api_view(['GET'])
@permission_classes([AllowAny])
def room_type_booked_ranges(request, pk):
    """
    GET /api/hotels/room-types/<pk>/booked-ranges/ — public, read-only.

    The storefront only lets a guest pick a RoomType (e.g. "Deluxe Room"),
    not a specific Room — so a per-room "booked ranges" endpoint like
    rentals.booked_ranges wouldn't tell the guest anything useful; a date
    can be free on Room 101 but not Room 102. Instead this returns the
    date ranges where EVERY available room of this type is booked at once
    (a sweep over each room's overlapping pending/confirmed/active
    bookings), so the booking modal can disable/flag only genuinely
    fully-booked dates rather than over- or under-reporting availability.
    """
    try:
        room_type = RoomType.objects.get(pk=pk, tenant=request.tenant)
    except RoomType.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=404)

    rooms = list(Room.objects.filter(
        tenant=request.tenant, room_type=room_type, status='available',
    ).values_list('id', flat=True))
    total_rooms = len(rooms)
    if total_rooms == 0:
        # No available rooms at all of this type — the whole thing reads
        # as "fully booked" going forward, but there's no meaningful date
        # range to report (nothing is actually reserved); let the frontend
        # treat an empty ranges list + total_rooms == 0 as "unavailable".
        return Response({'room_type': room_type.name, 'total_rooms': 0, 'ranges': []})

    bookings = RoomBooking.objects.filter(
        room_id__in=rooms,
        booking__status__in=('pending', 'confirmed', 'active'),
    ).values_list('booking__start_date', 'booking__end_date')

    # Sweep-line: +1 occupied room at each start_date, -1 at each end_date
    # (checkout day itself is free, matching the exclusive-end convention
    # used by is_room_available's start<end / end>start overlap check).
    events = {}
    for start_date, end_date in bookings:
        events[start_date] = events.get(start_date, 0) + 1
        events[end_date] = events.get(end_date, 0) - 1

    ranges = []
    if events:
        occupied = 0
        range_start = None
        for d in sorted(events.keys()):
            occupied += events[d]
            if occupied >= total_rooms and range_start is None:
                range_start = d
            elif occupied < total_rooms and range_start is not None:
                ranges.append({'start_date': range_start, 'end_date': d})
                range_start = None
        # An open range (fully booked with no further checkout in the swept
        # events) shouldn't happen in practice since every booking has an
        # end_date, but guard defensively rather than silently dropping it.
        if range_start is not None:
            ranges.append({'start_date': range_start, 'end_date': sorted(events.keys())[-1]})

    return Response({
        'room_type': room_type.name,
        'total_rooms': total_rooms,
        'ranges': ranges,
    })


@api_view(['GET'])
@permission_classes([IsTenantOwner])
def rooms_calendar(request):
    """
    GET /api/hotels/rooms/calendar/ — owner only.

    Unlike room_type_booked_ranges (which aggregates across every room of a
    type for the public storefront), this returns each individual Room with
    its own list of booked date ranges — exactly what the admin calendar
    needs to show "Room 101 is booked from X to Y" per room, so staff can
    see at a glance which specific rooms are free on which dates and avoid
    double-booking.

    Optional query params:
      room_type_id — filter to a single room type
      from / to    — ISO date strings; only ranges overlapping this window
                     are returned (defaults to no filtering — all upcoming
                     and past active bookings are included).
    """
    rooms = Room.objects.filter(tenant=request.tenant).select_related('room_type').order_by(
        'room_type__name', 'floor', 'room_number'
    )
    room_type_id = request.query_params.get('room_type_id')
    if room_type_id:
        rooms = rooms.filter(room_type_id=room_type_id)

    room_ids = list(rooms.values_list('id', flat=True))

    bookings_qs = RoomBooking.objects.filter(
        room_id__in=room_ids,
        booking__status__in=('pending', 'confirmed', 'active'),
    ).select_related('booking').values(
        'room_id', 'booking__id', 'booking__start_date', 'booking__end_date',
        'booking__guest_name', 'booking__guest_phone', 'booking__status',
    )

    from_param = request.query_params.get('from')
    to_param = request.query_params.get('to')
    from datetime import date as _date
    window_start = window_end = None
    if from_param:
        try:
            window_start = _date.fromisoformat(from_param)
        except ValueError:
            return Response({'detail': 'Invalid "from" date, expected YYYY-MM-DD.'}, status=400)
    if to_param:
        try:
            window_end = _date.fromisoformat(to_param)
        except ValueError:
            return Response({'detail': 'Invalid "to" date, expected YYYY-MM-DD.'}, status=400)

    ranges_by_room = {}
    for b in bookings_qs:
        sd, ed = b['booking__start_date'], b['booking__end_date']
        if sd is None or ed is None:
            continue
        if window_start and ed <= window_start:
            continue
        if window_end and sd >= window_end:
            continue
        ranges_by_room.setdefault(b['room_id'], []).append({
            'booking_id': str(b['booking__id']),
            'start_date': sd,
            'end_date': ed,
            'guest_name': b['booking__guest_name'],
            'guest_phone': b['booking__guest_phone'],
            'status': b['booking__status'],
        })

    for room_ranges in ranges_by_room.values():
        room_ranges.sort(key=lambda r: r['start_date'])

    data = [{
        'room_id': str(room.pk),
        'room_number': room.room_number,
        'floor': room.floor,
        'room_type_id': str(room.room_type_id),
        'room_type_name': room.room_type.name,
        'status': room.status,
        'booked_ranges': ranges_by_room.get(room.pk, []),
    } for room in rooms]

    return Response({'rooms': data})
