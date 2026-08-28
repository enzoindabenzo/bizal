from django.db import transaction
from rest_framework import generics
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from tenants.permissions import IsTenantOwner, HasTenantFeature
from tenants.limits import enforce_max_listings
from .models import RentalItem
from .serializers import RentalItemSerializer

# Rentals are a booking-heavy vertical: management endpoints require the
# tenant's plan to include 'bookings' (public read stays open).
BOOKINGS_FEATURE = HasTenantFeature('bookings')


class RentalItemListView(generics.ListCreateAPIView):
    """
    GET  /api/rentals/ — public, only available items
    POST /api/rentals/ — owner only, creates a rental item

    NOTE: mirrors the same consolidation done in inventory/views.py
    (ProductListView/ProductDetailView) — this used to be three separate
    endpoints (list-only here, a create-only `/create/` view, and a
    separate `/<pk>/manage/` retrieve-update-destroy view), which meant
    the tenant admin UI's POST /rentals/ and PATCH/DELETE /rentals/<id>/
    calls (matching every other resource's URL convention) were silently
    hitting 405 Method Not Allowed. `/create/` and `/<pk>/manage/` are
    kept as aliases below purely for backward compatibility.
    """
    serializer_class = RentalItemSerializer
    # NOTE: previously declared search_fields/filterset_fields here, but
    # django-filter isn't installed and no SearchFilter/DjangoFilterBackend
    # is configured in filter_backends — those attributes were silently
    # doing nothing. Filtering is handled manually below instead, alongside
    # the rental_type/city filters that already worked the same way.

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsTenantOwner(), BOOKINGS_FEATURE()]
        return [AllowAny()]

    def get_queryset(self):
        # Owner-authenticated POST doesn't read this queryset, but GET
        # (public) must only ever see available items.
        qs = RentalItem.objects.filter(tenant=self.request.tenant, status='available')
        rental_type = self.request.query_params.get('rental_type')
        city = self.request.query_params.get('city')
        search = self.request.query_params.get('search')
        if rental_type:
            qs = qs.filter(rental_type=rental_type)
        if city:
            qs = qs.filter(city__icontains=city)
        if search:
            from django.db.models import Q
            qs = qs.filter(
                Q(name__icontains=search) |
                Q(city__icontains=search) |
                Q(description__icontains=search)
            )
        return qs

    def perform_create(self, serializer):
        with transaction.atomic():
            enforce_max_listings(self.request.tenant, RentalItem)
            serializer.save(tenant=self.request.tenant)


class RentalFeaturedListView(generics.ListAPIView):
    """Public list of featured, available rental items (for storefront highlights)."""
    serializer_class = RentalItemSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        return RentalItem.objects.filter(
            tenant=self.request.tenant, status='available', is_featured=True,
        )


class RentalItemDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET                 /api/rentals/<pk>/ — public, only available items
    PUT/PATCH/DELETE    /api/rentals/<pk>/ — owner only, any item
    (including unavailable/maintenance ones)
    """
    serializer_class = RentalItemSerializer

    def get_permissions(self):
        if self.request.method == 'GET':
            return [AllowAny()]
        return [IsTenantOwner(), BOOKINGS_FEATURE()]

    def get_queryset(self):
        qs = RentalItem.objects.filter(tenant=self.request.tenant)
        if self.request.method == 'GET':
            qs = qs.filter(status='available')
        return qs


@api_view(['GET'])
@permission_classes([AllowAny])
def check_availability(request, pk):
    start = request.query_params.get('start_date')
    end = request.query_params.get('end_date')
    if not start or not end:
        return Response({'detail': 'start_date and end_date required.'}, status=400)
    import datetime
    try:
        datetime.date.fromisoformat(start)
        datetime.date.fromisoformat(end)
    except ValueError:
        return Response({'detail': 'Invalid date format. Use YYYY-MM-DD.'}, status=400)
    try:
        item = RentalItem.objects.get(pk=pk, tenant=request.tenant)
    except RentalItem.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=404)
    available = item.is_available_for(start, end)
    return Response({'available': available, 'item': item.name})


@api_view(['GET'])
@permission_classes([AllowAny])
def booked_ranges(request, pk):
    """
    GET /api/rentals/<pk>/booked-ranges/ — public, read-only.

    Returns the existing pending/confirmed/active booking date ranges for
    this rental item, so the storefront booking modal can show "already
    booked" hints and disable those dates in the date picker instead of the
    customer only finding out after submitting (and hitting the
    is_available_for() overlap check in BookingSerializer.validate()).
    """
    try:
        item = RentalItem.objects.get(pk=pk, tenant=request.tenant)
    except RentalItem.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=404)

    from bookings.models import Booking
    qs = Booking.objects.filter(
        tenant=request.tenant,
        resource_id=str(item.pk),
        resource_type='rental_item',
        status__in=('pending', 'confirmed', 'active'),
    ).order_by('start_date').values('start_date', 'end_date')
    return Response({
        'item': item.name,
        'ranges': [{'start_date': r['start_date'], 'end_date': r['end_date']} for r in qs],
    })


# ── Backward-compatible aliases ─────────────────────────────────────────────
# Kept so existing callers/tests targeting /create/ and /<pk>/manage/
# continue to work unchanged. New code should use the consolidated
# endpoints above instead.
RentalItemManageView = RentalItemListView
RentalItemUpdateView = RentalItemDetailView
