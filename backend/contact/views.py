import logging

logger = logging.getLogger(__name__)

from rest_framework import generics, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from django.core.mail import send_mail
from django.conf import settings
from django.utils.decorators import method_decorator
from tenants.permissions import HasTenantRole, TenantDomainOnly, HasTenantFeature
from bizal.ratelimit_utils import ratelimit_decorator
from notifications.tasks import notify_owner_async
from .models import ContactMessage, PlatformInquiry
from .serializers import ContactMessageSerializer, PlatformInquirySerializer


class ContactSubmitView(APIView):
    # HIGH-3 FIX: Require a valid tenant subdomain and the contact_form plan
    # feature. Without TenantDomainOnly, requests to the main domain
    # (request.tenant=None) reach serializer.save(tenant=None) and cause a
    # DB IntegrityError (tenant is NOT NULL). HasTenantFeature enforces the
    # plan gate that was already defined in PLAN_FEATURES but never applied.
    permission_classes = [AllowAny, TenantDomainOnly, HasTenantFeature('contact_form')]

    # Public, unauthenticated, no per-tenant plan limit — the most
    # spam-exposed POST endpoint in the app. 10/hour per IP is generous for
    # a genuine visitor contacting one business, but blocks naive spam bots.
    @method_decorator(ratelimit_decorator('10/h'))
    def post(self, request):
        serializer = ContactMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        msg = serializer.save(
            tenant=request.tenant,
            # Behind nginx, REMOTE_ADDR is the container IP (172.x.x.x).
            # Use X-Real-IP (set by nginx) to get the real client IP.
            ip_address=(
                request.META.get('HTTP_X_REAL_IP')
                or request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip()
                or request.META.get('REMOTE_ADDR')
            ),
        )
        # Notify tenant owner
        # NOTE on fail_silently=True here vs. fail_silently=False in
        # ContactReplyView below: this is the *visitor-facing* submission
        # path. The contact form save() above has already succeeded — the
        # message is safely in the DB — so a failed owner-notification
        # email must never surface as an error to the visitor (they'd see
        # a 5xx for something they did correctly). ContactReplyView is
        # *staff-facing*: a failed reply email IS the entire point of that
        # action, so it must surface (502) so staff know to retry or use
        # another channel. Same `send_mail` call, different audience and
        # different consequence of silent failure — hence the asymmetry.
        if request.tenant and request.tenant.email:
            send_mail(
                subject=f'New message from {msg.name}',
                message=msg.message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[request.tenant.email],
                fail_silently=True,
            )
        # In-app notification for owner/manager
        if request.tenant:
            notify_owner_async.delay(
                str(request.tenant.pk),
                'new_contact',
                f'New message from {msg.name}',
                msg.message[:200],
                metadata={'contact_id': str(msg.id)},
                idempotency_key=f'contact:{msg.id}',
            )
        return Response({'detail': 'Message sent.'}, status=status.HTTP_201_CREATED)


class PlatformContactSubmitView(APIView):
    """Tenant-agnostic contact endpoint for the main marketing site
    (bizal.al), which runs with no tenant subdomain. Stores submissions in
    PlatformInquiry (no tenant FK) and emails settings.ADMIN_EMAIL."""
    permission_classes = [AllowAny]

    @method_decorator(ratelimit_decorator('10/h'))
    def post(self, request):
        serializer = PlatformInquirySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        inquiry = serializer.save(
            ip_address=(
                request.META.get('HTTP_X_REAL_IP')
                or request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip()
                or request.META.get('REMOTE_ADDR')
            ),
        )
        send_mail(
            subject=f'[BizAL] New platform inquiry from {inquiry.name}',
            message=inquiry.message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[settings.ADMIN_EMAIL],
            fail_silently=True,
        )
        return Response({'detail': 'Message sent.'}, status=status.HTTP_201_CREATED)


class ContactMessageListView(generics.ListAPIView):
    serializer_class = ContactMessageSerializer
    permission_classes = [HasTenantRole('receptionist')]

    def get_queryset(self):
        return ContactMessage.objects.filter(tenant=self.request.tenant)


class ContactMessageDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = ContactMessageSerializer
    permission_classes = [HasTenantRole('receptionist')]

    def get_queryset(self):
        return ContactMessage.objects.filter(tenant=self.request.tenant)

    def perform_update(self, serializer):
        serializer.save(is_read=True)


class ContactReplyView(APIView):
    permission_classes = [HasTenantRole('receptionist')]

    def post(self, request, pk):
        try:
            msg = ContactMessage.objects.get(pk=pk, tenant=request.tenant)
        except ContactMessage.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=404)
        reply_text = request.data.get('reply', '')
        if not reply_text:
            return Response({'detail': 'Reply text required.'}, status=400)
        try:
            send_mail(
                subject=f'Re: {msg.subject or "Your message"}',
                message=reply_text,
                from_email=request.tenant.get_reply_from_email(),
                recipient_list=[msg.email],
                fail_silently=False,
            )
        except Exception as exc:
            logger.error(
                'ContactReplyView: SMTP failure for msg %s (tenant=%s): %s',
                pk, getattr(request.tenant, 'slug', '?'), exc,
                exc_info=True,
            )
            return Response(
                {'detail': 'Reply could not be sent due to a mail server error. Please try again later.'},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        from django.utils import timezone
        msg.replied_at = timezone.now()
        msg.save(update_fields=['replied_at'])
        return Response({'detail': 'Reply sent.'})
