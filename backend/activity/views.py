from rest_framework import generics
from rest_framework.pagination import PageNumberPagination
from tenants.permissions import IsTenantStaff
from .models import ActivityLog
from .serializers import ActivityLogSerializer


class _ActivityPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


class ActivityLogListView(generics.ListAPIView):
    """
    GET /api/activity/

    Recent activity for the current tenant — bookings confirmed/cancelled,
    invoices created, staff added/removed, etc. Any staff member (owner,
    manager, receptionist, accountant, staff) can view the feed; customers
    cannot.

    Optional filters:
      ?verb=booking.confirmed   — exact verb match
      ?target_type=booking      — only entries about a given object type
    """
    pagination_class = _ActivityPagination
    serializer_class = ActivityLogSerializer
    permission_classes = [IsTenantStaff]

    def get_queryset(self):
        qs = ActivityLog.objects.filter(tenant=self.request.tenant).select_related('actor')

        verb = self.request.query_params.get('verb')
        if verb:
            qs = qs.filter(verb=verb)

        target_type = self.request.query_params.get('target_type')
        if target_type:
            qs = qs.filter(target_type=target_type)

        return qs
