from rest_framework import serializers, generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.core.mail import send_mail
from django.conf import settings
from tenants.permissions import IsTenantOwner
from .models import ContactMessage


class ContactMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactMessage
        fields = ('id', 'name', 'email', 'phone', 'subject', 'message', 'is_read', 'replied_at', 'created_at')
        read_only_fields = ('id', 'is_read', 'replied_at', 'created_at')


class ContactSubmitView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ContactMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        msg = serializer.save(
            tenant=request.tenant,
            ip_address=request.META.get('REMOTE_ADDR'),
        )
        # Notify tenant owner
        if request.tenant and request.tenant.email:
            send_mail(
                subject=f'New message from {msg.name}',
                message=msg.message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[request.tenant.email],
                fail_silently=True,
            )
        return Response({'detail': 'Message sent.'}, status=status.HTTP_201_CREATED)


class ContactMessageListView(generics.ListAPIView):
    serializer_class = ContactMessageSerializer
    permission_classes = [IsTenantOwner]

    def get_queryset(self):
        return ContactMessage.objects.filter(tenant=self.request.tenant)


class ContactMessageDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = ContactMessageSerializer
    permission_classes = [IsTenantOwner]

    def get_queryset(self):
        return ContactMessage.objects.filter(tenant=self.request.tenant)

    def perform_update(self, serializer):
        serializer.save(is_read=True)


class ContactReplyView(APIView):
    permission_classes = [IsTenantOwner]

    def post(self, request, pk):
        try:
            msg = ContactMessage.objects.get(pk=pk, tenant=request.tenant)
        except ContactMessage.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=404)
        reply_text = request.data.get('reply', '')
        if not reply_text:
            return Response({'detail': 'Reply text required.'}, status=400)
        send_mail(
            subject=f'Re: {msg.subject or "Your message"}',
            message=reply_text,
            from_email=request.tenant.email or settings.DEFAULT_FROM_EMAIL,
            recipient_list=[msg.email],
            fail_silently=False,
        )
        from django.utils import timezone
        msg.replied_at = timezone.now()
        msg.save(update_fields=['replied_at'])
        return Response({'detail': 'Reply sent.'})
