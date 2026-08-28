from rest_framework import generics
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from tenants.permissions import TenantDomainOnly
from .models import Notification
from .serializers import NotificationSerializer

# In-app notifications are available on all plans (the flag 'notifications_sms'
# in PLAN_FEATURES gates SMS delivery only, not in-app notifications).
# We require IsAuthenticated + TenantDomainOnly (must be on a tenant subdomain,
# not the main domain) — no feature flag needed here.
_notifications_permissions = [IsAuthenticated, TenantDomainOnly]


class NotificationListView(generics.ListAPIView):
    serializer_class = NotificationSerializer
    permission_classes = _notifications_permissions

    def get_queryset(self):
        qs = Notification.objects.filter(
            tenant=self.request.tenant, user=self.request.user
        )
        # Optional filters: ?notification_type=chatbot_handoff&unread=true
        ntype = self.request.query_params.get('notification_type', '').strip()
        if ntype:
            qs = qs.filter(notification_type=ntype)
        unread = self.request.query_params.get('unread', '').lower()
        if unread == 'true':
            qs = qs.filter(is_read=False)
        return qs


@api_view(['GET'])
@permission_classes(_notifications_permissions)
def unread_count(request):
    count = Notification.objects.filter(
        tenant=request.tenant, user=request.user, is_read=False
    ).count()
    return Response({'unread_count': count})


@api_view(['POST'])
@permission_classes(_notifications_permissions)
def mark_all_read(request):
    Notification.objects.filter(
        tenant=request.tenant, user=request.user, is_read=False
    ).update(is_read=True)
    return Response({'detail': 'All marked as read.'})


@api_view(['POST'])
@permission_classes(_notifications_permissions)
def mark_read(request, pk):
    try:
        n = Notification.objects.get(pk=pk, user=request.user, tenant=request.tenant)
        n.is_read = True
        n.save(update_fields=['is_read'])
    except Notification.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=404)
    return Response({'detail': 'Marked as read.'})
