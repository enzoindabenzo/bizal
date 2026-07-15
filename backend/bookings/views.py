import logging

from django.db import transaction
from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from tenants.permissions import HasTenantRole, get_effective_role
from .models import Booking
from .serializers import BookingSerializer
from billing.loyalty import award_points

logger = logging.getLogger(__name__)

# HIGH-1 FIX: Enforce valid status transitions to prevent logically invalid
# reversals (e.g. cancelled → confirmed, completed → active).  Terminal states
# have an empty set — no outbound transitions are permitted.  This closes the
# "ghost unavailability" gap where a cancelled booking moved back to confirmed
# would re-enter availability overlap detection without any paper trail.
#
# MEDIUM-3 FIX: Co-locate the valid-status set here so it is derived from the
# same authoritative data source as the transition map, avoiding the latent
# OptGroup edge-case in the dynamic _meta.get_field('status').choices introspection.
_STATUS_CHOICES = {s[0] for s in Booking._meta.get_field('status').choices}

VALID_TRANSITIONS = {
    'pending':   {'confirmed', 'cancelled', 'no_show'},
    'confirmed': {'active', 'completed', 'cancelled', 'no_show'},
    'active':    {'completed', 'cancelled', 'no_show'},
    'completed': set(),   # terminal
    'cancelled': set(),   # terminal
    'no_show':   set(),   # terminal
}


class BookingListCreateView(generics.ListCreateAPIView):
    serializer_class = BookingSerializer

    def get_permissions(self):
        if self.request.method == 'POST':
            return [AllowAny()]
        return [IsAuthenticated()]

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return Booking.objects.none()
        qs = Booking.objects.filter(tenant=self.request.tenant).select_related('user')
        # LOW-3 FIX: Use get_effective_role() instead of getattr(user, 'role', '').
        # The authoritative function respects StaffMember.is_active, so a
        # deactivated staff member who retains User.role='staff' can no longer
        # see all bookings.  getattr(user, 'role') bypassed that guard.
        if not (user.is_superuser or get_effective_role(user, self.request.tenant) is not None):
            qs = qs.filter(user=user)
        return qs

    def create(self, request, *args, **kwargs):
        # MED-3 FIX: explicitly reject requests with no resolved tenant (e.g. a
        # superadmin hitting this endpoint from the main domain). Without this,
        # `tenant and not tenant.has_feature(...)` below is falsy when tenant is
        # None (so the feature check is skipped), and perform_create() then
        # calls serializer.save(tenant=None, ...), which hits the NOT NULL
        # constraint on Booking.tenant and surfaces as an unhandled 500 instead
        # of a clean 400. orders/views.py already has the equivalent guard.
        if not request.tenant:
            return Response(
                {'detail': 'Bookings must be made from a tenant subdomain.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Guard: reject bookings for tenants whose plan doesn't include bookings.
        # This check must live in create() (not perform_create) so we can return
        # a proper 403 response before the serializer runs.
        tenant = request.tenant
        if tenant and not tenant.has_feature('bookings'):
            return Response(
                {'detail': 'Bookings are not available on this tenant\'s plan.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        # FIX: Wrap is_valid()+save() in a single transaction so the
        # select_for_update() lock in BookingSerializer.validate() is held all
        # the way through the INSERT. Previously the inner atomic() in validate()
        # released the lock before perform_create() ran, making TOCTOU
        # protection for room/rental double-booking completely ineffective.
        with transaction.atomic():
            return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        user = self.request.user if self.request.user.is_authenticated else None
        booking = serializer.save(tenant=self.request.tenant, user=user)

        # Write a RoomBooking join row so is_room_available() can actually
        # detect overlaps. Without this the RoomBooking table stays empty and
        # every availability check returns True regardless of existing bookings.
        if booking.booking_type == 'room_booking' and booking.resource_type == 'room' and booking.resource_id:
            try:
                from hotels.models import Room, RoomBooking
                from django.core.exceptions import ObjectDoesNotExist
                room = Room.objects.get(pk=booking.resource_id, tenant=booking.tenant)
                RoomBooking.objects.get_or_create(booking=booking, defaults={'room': room})
            except (Room.DoesNotExist, ObjectDoesNotExist):
                # Expected: room validated in serializer but may have been deleted between validate() and save()
                pass
            except Exception:
                # MEDIUM-4 FIX: unexpected failure (DB error, IntegrityError, schema change) must be logged.
                # Without this row, is_room_available() returns True for all queries and double-booking
                # protection is silently disabled for this booking.
                logger.exception(
                    'perform_create: failed to create RoomBooking linkage for booking %s (resource_id=%s) '
                    '— double-booking protection is degraded for this room until the row is manually created',
                    booking.pk, booking.resource_id,
                )

        # In-app notification for tenant owner — dispatched async so the
        # DB query for owner/manager users doesn't block the HTTP response.
        if self.request.tenant:
            from notifications.tasks import notify_owner_async
            guest = booking.guest_name or (user.display_name if user else 'Guest')
            notify_owner_async.delay(
                str(self.request.tenant.pk),
                'booking_confirmed',
                'New Booking',
                f'{guest} made a {booking.get_booking_type_display()} booking.',
                metadata={'booking_id': str(booking.id)},
                idempotency_key=f'booking:{booking.id}',
            )


class BookingDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = BookingSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'patch']  # no PUT

    def get_queryset(self):
        qs = Booking.objects.filter(tenant=self.request.tenant).select_related('user')
        user = self.request.user
        # Staff/owner/manager see all bookings; customers only their own
        # LOW-1 FIX (v52): Use get_effective_role() so deactivated staff (is_active=False
        # on StaffMember) cannot retrieve arbitrary bookings. getattr(user,'role') bypassed
        # the StaffMember.is_active guard enforced by get_effective_role().
        if not (user.is_superuser or get_effective_role(user, self.request.tenant) is not None):
            qs = qs.filter(user=user)
        return qs

    def partial_update(self, request, *args, **kwargs):
        # FIX: Wrap is_valid()+save() in a single transaction, mirroring
        # BookingListCreateView.create(). Without this, the select_for_update()
        # lock taken in BookingSerializer.validate() is released as soon as
        # that inner atomic() block exits — before this view's save() writes
        # the new dates — so two concurrent reschedule requests can each pass
        # the overlap check and produce overlapping room/rental bookings.
        #
        # NOTE: 'status' is a read_only field on BookingSerializer (by
        # design — status transitions go through admin_update_booking,
        # which validates the transition and triggers side effects like
        # loyalty accrual). A PATCH here can reschedule dates/notes/guest
        # info but can never change status, so there's no status-change
        # hook to add in this method.
        kwargs['partial'] = True
        with transaction.atomic():
            return super().update(request, *args, **kwargs)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def cancel_booking(request, pk):
    # LOW-1 FIX (v52): Use get_effective_role() so deactivated staff cannot cancel
    # arbitrary bookings. Mirrors the fix applied to BookingDetailView above.
    is_owner = request.user.is_superuser or get_effective_role(request.user, request.tenant) is not None

    try:
        booking = Booking.objects.get(pk=pk, tenant=request.tenant)
    except Booking.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=404)

    if not is_owner and booking.user_id != request.user.id:
        return Response({'detail': 'You do not have permission to cancel this booking.'}, status=403)

    if booking.status in ('completed', 'cancelled', 'no_show'):
        return Response({'detail': f'Cannot cancel a {booking.status} booking.'}, status=400)
    booking.status = 'cancelled'
    # LOW-1 FIX: include 'updated_at' explicitly — Django 4.2 injects auto_now
    # fields even when omitted from update_fields, but the behaviour is
    # version-dependent. Explicit is correct and consistent with MeDeleteView.
    booking.save(update_fields=['status', 'updated_at'])

    from activity.utils import log_activity
    log_activity(
        tenant=request.tenant,
        actor=request.user,
        verb='booking.cancelled',
        description=f'Cancelled booking for {booking.guest_name or "a customer"}',
        target_type='booking',
        target_id=booking.id,
    )

    return Response({'detail': 'Booking cancelled.'})


@api_view(['PATCH'])
@permission_classes([HasTenantRole('receptionist', 'staff')])
def admin_update_booking(request, pk):
    try:
        booking = Booking.objects.get(pk=pk, tenant=request.tenant)
    except Booking.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=404)
    new_status = request.data.get('status')
    notes = request.data.get('internal_notes')
    new_price = request.data.get('total_price')
    # SECURITY FIX: total_price is read-only on BookingSerializer and is
    # normally computed server-side from the booking's resource (service/
    # rental/room). But table reservations, classes, events, and deliveries
    # have no fixed priced resource — for those, staff need a way to record
    # the actual final amount before marking a booking 'completed', since
    # that's what feeds award_points(). This is staff-only (this view already
    # requires HasTenantRole('receptionist', 'staff')), so — unlike the old
    # customer-writable field — it can't be used by a guest to inflate their
    # own loyalty points.
    if new_price is not None:
        from decimal import Decimal, InvalidOperation
        try:
            new_price = Decimal(str(new_price))
            if new_price < 0:
                return Response({'detail': 'total_price cannot be negative.'}, status=400)
        except InvalidOperation:
            return Response({'detail': 'total_price must be a valid number.'}, status=400)
        booking.total_price = new_price
    if new_status:
        if new_status not in _STATUS_CHOICES:
            return Response(
                {'detail': f'Invalid status. Choices: {sorted(_STATUS_CHOICES)}'},
                status=400,
            )
        # HIGH-1 FIX: Enforce the transition map.  Terminal states (completed,
        # cancelled, no_show) have an empty allowed set, so any transition out
        # of them is rejected.  This prevents ghost-unavailability caused by
        # reactivating a cancelled or completed booking.
        allowed = VALID_TRANSITIONS.get(booking.status, set())
        if new_status not in allowed:
            return Response(
                {'detail': f'Cannot transition from "{booking.status}" to "{new_status}".'},
                status=400,
            )
        booking.status = new_status
    if notes:
        booking.internal_notes = notes

    # Only write to the DB (and only log/notify below) if something was
    # actually supplied. An empty PATCH body previously still triggered a
    # save (bumping updated_at for no reason), an activity log entry with
    # new_status=None, and a confirmation-email check — all no-ops with
    # side effects that shouldn't exist for a request that changed nothing.
    if not (new_status or notes or new_price is not None):
        return Response(BookingSerializer(booking).data)

    with transaction.atomic():
        booking.save()

        if new_status == 'completed':
            # total_price has default=0 (never None). Award points only when there
            # is a registered user and a positive price. Free bookings (price=0)
            # are valid and expected — no log needed for them.
            if booking.user_id and booking.total_price > 0:
                award_points(
                    request.tenant, booking.user, booking.total_price,
                    reason=f'Booking #{str(booking.id)[:8]}',
                    source_type='booking', source_id=booking.id,
                )
            elif not booking.user_id and booking.total_price > 0:
                logger.info(
                    'award_points skipped for booking %s: guest booking (no user account), '
                    'price=%s', booking.id, booking.total_price,
                )
            # total_price == 0: free/complimentary booking — no points expected, no log needed

    from activity.utils import log_activity
    if new_status:
        log_activity(
            tenant=request.tenant,
            actor=request.user,
            verb='booking.status_changed',
            description=f'Updated booking for {booking.guest_name or "a customer"} to "{new_status}"',
            target_type='booking',
            target_id=booking.id,
            metadata={'status': new_status},
        )

    # Send confirmation email when owner confirms a booking
    if new_status == 'confirmed':
        try:
            from notifications.tasks import send_booking_confirmation_email
            send_booking_confirmation_email.delay(str(booking.id))
        except Exception:
            pass  # Never let email failure break the API response

    return Response(BookingSerializer(booking).data)
