from rest_framework import generics, serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ('id', 'notification_type', 'title', 'body', 'is_read', 'metadata', 'created_at')
        read_only_fields = ('id', 'created_at')


class NotificationListView(generics.ListAPIView):
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Notification.objects.filter(
            tenant=self.request.tenant, user=self.request.user
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def mark_all_read(request):
    Notification.objects.filter(
        tenant=request.tenant, user=request.user, is_read=False
    ).update(is_read=True)
    return Response({'detail': 'All marked as read.'})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def mark_read(request, pk):
    try:
        n = Notification.objects.get(pk=pk, user=request.user, tenant=request.tenant)
        n.is_read = True
        n.save(update_fields=['is_read'])
    except Notification.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=404)
    return Response({'detail': 'Marked as read.'})
