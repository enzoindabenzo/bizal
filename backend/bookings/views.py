from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from tenants.permissions import IsTenantOwner
from .models import Booking
from .serializers import BookingSerializer


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
        qs = Booking.objects.filter(tenant=self.request.tenant)
        if not (user.is_superuser or getattr(user, 'role', '') in ('owner', 'manager', 'staff')):
            qs = qs.filter(user=user)
        return qs

    def perform_create(self, serializer):
        user = self.request.user if self.request.user.is_authenticated else None
        serializer.save(tenant=self.request.tenant, user=user)


class BookingDetailView(generics.RetrieveAPIView):
    serializer_class = BookingSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Booking.objects.filter(tenant=self.request.tenant)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def cancel_booking(request, pk):
    try:
        booking = Booking.objects.get(pk=pk, tenant=request.tenant)
    except Booking.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=404)
    if booking.status in ('completed', 'cancelled'):
        return Response({'detail': f'Cannot cancel a {booking.status} booking.'}, status=400)
    booking.status = 'cancelled'
    booking.save(update_fields=['status'])
    return Response({'detail': 'Booking cancelled.'})


@api_view(['PATCH'])
@permission_classes([IsTenantOwner])
def admin_update_booking(request, pk):
    try:
        booking = Booking.objects.get(pk=pk, tenant=request.tenant)
    except Booking.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=404)
    new_status = request.data.get('status')
    notes = request.data.get('internal_notes')
    if new_status:
        booking.status = new_status
    if notes:
        booking.internal_notes = notes
    booking.save()
    return Response(BookingSerializer(booking).data)
