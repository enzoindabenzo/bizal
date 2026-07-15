from django.db import transaction
from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from bizal.throttles import PublicReadThrottle
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from tenants.permissions import IsTenantOwner, IsTenantStaff, HasTenantFeature, get_effective_role
from tenants.limits import enforce_max_listings
from .models import ServiceProvider, Service, Appointment
from .serializers import ServiceProviderSerializer, ServiceSerializer, AppointmentSerializer
from notifications.tasks import notify_owner_async

# Appointments are a booking-heavy vertical: management endpoints require
# the tenant's plan to include 'bookings' (public read stays open).
BOOKINGS_FEATURE = HasTenantFeature('bookings')

# HIGH-1 FIX (v54): Mirror the VALID_TRANSITIONS guard already applied to
# admin_update_booking and admin_update_order. Without this map,
# update_appointment_status accepted any valid status string and wrote it
# unconditionally — allowing terminal states (completed, cancelled, no_show)
# to be re-opened. Re-opening a completed appointment enables double loyalty-
# point accrual; re-opening cancelled/no_show recreates ghost-unavailability
# for the same provider time-slot. Terminal states have an empty allowed set.
APPOINTMENT_VALID_TRANSITIONS = {
    'pending':   {'confirmed', 'cancelled', 'no_show'},
    'confirmed': {'completed', 'cancelled', 'no_show'},
    'completed': set(),   # terminal
    'cancelled': set(),   # terminal
    'no_show':   set(),   # terminal
}
_APPOINTMENT_STATUS_CHOICES = {s[0] for s in Appointment._meta.get_field('status').choices}


# ── Public views ─────────────────────────────────────────────

class ProviderListView(generics.ListAPIView):
    throttle_classes = [PublicReadThrottle]
    serializer_class = ServiceProviderSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        return ServiceProvider.objects.filter(tenant=self.request.tenant, is_active=True)


class ServiceListView(generics.ListAPIView):
    throttle_classes = [PublicReadThrottle]
    serializer_class = ServiceSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        return Service.objects.filter(tenant=self.request.tenant, is_active=True)


class AppointmentCreateView(generics.CreateAPIView):
    serializer_class = AppointmentSerializer
    permission_classes = [AllowAny]

    def create(self, request, *args, **kwargs):
        # Guard: reject appointment creation for tenants whose plan doesn't
        # include bookings. Mirrors the equivalent check in
        # bookings/views.py's BookingListCreateView.create() and
        # hotels/views.py's RoomBookingListCreateView.create().
        if not request.tenant:
            return Response(
                {'detail': 'Appointments must be booked from a tenant subdomain.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not request.tenant.has_feature('bookings'):
            return Response(
                {'detail': "Bookings are not available on this tenant's plan."},
                status=status.HTTP_403_FORBIDDEN,
            )
        # FIX: Wrap is_valid()+save() in a single transaction so the
        # select_for_update() lock on the ServiceProvider row in
        # AppointmentSerializer.validate() is held all the way through the
        # INSERT. Previously the inner atomic() in validate() released the lock
        # before perform_create() ran, leaving the double-booking race open.
        with transaction.atomic():
            return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        user = self.request.user if self.request.user.is_authenticated else None
        appointment = serializer.save(tenant=self.request.tenant, user=user)
        # Notify tenant owner
        if self.request.tenant:
            notify_owner_async.delay(
                str(self.request.tenant.pk),
                'appointment_new',
                'New Appointment',
                f"{appointment.guest_name or 'Guest'} booked {appointment.service.name} on {appointment.date}.",
                metadata={'appointment_id': str(appointment.id)},
                idempotency_key=f'appointment:{appointment.id}',
            )


# ── Owner / staff views ──────────────────────────────────────

class AppointmentListView(generics.ListAPIView):
    serializer_class = AppointmentSerializer
    permission_classes = [IsTenantStaff]

    def get_queryset(self):
        qs = Appointment.objects.filter(tenant=self.request.tenant).select_related('service', 'provider')
        date_filter = self.request.query_params.get('date')
        status_filter = self.request.query_params.get('status')
        provider_filter = self.request.query_params.get('provider')
        if date_filter:
            qs = qs.filter(date=date_filter)
        if status_filter:
            qs = qs.filter(status=status_filter)
        if provider_filter:
            qs = qs.filter(provider_id=provider_filter)
        return qs


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def cancel_appointment(request, pk):
    """Customer or owner cancels an appointment."""
    # Verify the user belongs to THIS tenant before granting owner access.
    # Without this check an owner of Tenant A could cancel Tenant B's
    # appointments by guessing the UUID — the lookup below already scopes
    # by request.tenant, but the role check must also confirm the user is
    # staff of that same tenant.
    # LOW-2 FIX (v54): Use get_effective_role() so deactivated staff
    # (StaffMember.is_active=False) cannot cancel arbitrary appointments.
    # The previous check read request.user.role directly, which retains
    # 'staff' on the User row even after StaffMember soft-deactivation,
    # bypassing the StaffMember.is_active guard. Mirrors the fix applied
    # to cancel_booking in v52.
    is_owner = (
        request.user.is_superuser
        or get_effective_role(request.user, request.tenant) is not None
    )

    try:
        appt = Appointment.objects.get(pk=pk, tenant=request.tenant)
    except Appointment.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

    if not is_owner and appt.user_id != request.user.id:
        return Response({'detail': 'You do not have permission to cancel this appointment.'}, status=status.HTTP_403_FORBIDDEN)

    # LOW-1 FIX (v54): Add 'no_show' to the terminal-state guard.
    # Mirrors the identical fix applied to cancel_booking in v53.
    if appt.status in ('cancelled', 'completed', 'no_show'):
        return Response({'detail': f'Cannot cancel a {appt.status} appointment.'}, status=status.HTTP_400_BAD_REQUEST)

    appt.status = 'cancelled'
    appt.save(update_fields=['status', 'updated_at'])
    return Response({'detail': 'Appointment cancelled.'})


@api_view(['PATCH'])
@permission_classes([IsTenantStaff])
def update_appointment_status(request, pk):
    """Staff updates appointment status (confirm, complete, no_show, etc.)."""
    try:
        appt = Appointment.objects.get(pk=pk, tenant=request.tenant)
    except Appointment.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

    new_status = request.data.get('status')
    if new_status not in _APPOINTMENT_STATUS_CHOICES:
        return Response(
            {'detail': f'Invalid status. Choices: {sorted(_APPOINTMENT_STATUS_CHOICES)}'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    # HIGH-1 FIX (v54): Enforce valid transition map. Terminal states
    # (completed, cancelled, no_show) have an empty allowed set — no
    # outbound transitions permitted. Without this, staff could re-open
    # a completed appointment (enabling double loyalty-point accrual) or
    # a cancelled/no_show slot (recreating ghost provider unavailability).
    allowed = APPOINTMENT_VALID_TRANSITIONS.get(appt.status, set())
    if new_status not in allowed:
        return Response(
            {'detail': f'Cannot transition from "{appt.status}" to "{new_status}".'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    appt.status = new_status
    appt.save(update_fields=['status', 'updated_at'])
    return Response(AppointmentSerializer(appt).data)


# ── Service & Provider management ────────────────────────────

class ServiceManageView(generics.ListCreateAPIView):
    serializer_class = ServiceSerializer
    permission_classes = [IsTenantOwner, BOOKINGS_FEATURE]

    def get_queryset(self):
        return Service.objects.filter(tenant=self.request.tenant)

    def perform_create(self, serializer):
        with transaction.atomic():
            enforce_max_listings(self.request.tenant, Service)
            serializer.save(tenant=self.request.tenant)


class ServiceDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ServiceSerializer
    permission_classes = [IsTenantOwner, BOOKINGS_FEATURE]

    def get_queryset(self):
        return Service.objects.filter(tenant=self.request.tenant)


class ProviderManageView(generics.ListCreateAPIView):
    serializer_class = ServiceProviderSerializer
    permission_classes = [IsTenantOwner, BOOKINGS_FEATURE]

    def get_queryset(self):
        return ServiceProvider.objects.filter(tenant=self.request.tenant)

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)


class ProviderDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ServiceProviderSerializer
    permission_classes = [IsTenantOwner, BOOKINGS_FEATURE]

    def get_queryset(self):
        return ServiceProvider.objects.filter(tenant=self.request.tenant)
