import stripe
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework import status

from tenants.models import Tenant, PLAN_PRO, PLAN_ENTERPRISE
from tenants.permissions import IsTenantOwner
from .models import Payment

stripe.api_key = settings.STRIPE_SECRET_KEY

PLAN_PRICE_MAP = {
    PLAN_PRO: settings.STRIPE_PRICE_PRO,
    PLAN_ENTERPRISE: settings.STRIPE_PRICE_ENTERPRISE,
}


@api_view(['POST'])
@permission_classes([IsTenantOwner])
def subscribe(request):
    plan = request.data.get('plan')
    if plan not in PLAN_PRICE_MAP:
        return Response({'detail': 'Invalid plan.'}, status=status.HTTP_400_BAD_REQUEST)
    if not request.tenant:
        return Response({'detail': 'No tenant.'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        session = stripe.checkout.Session.create(
            mode='subscription',
            payment_method_types=['card'],
            line_items=[{'price': PLAN_PRICE_MAP[plan], 'quantity': 1}],
            success_url=f"{settings.FRONTEND_BASE_URL}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{settings.FRONTEND_BASE_URL}/billing/cancel",
            metadata={'tenant_slug': request.tenant.slug, 'plan': plan},
        )
        return Response({'checkout_url': session.url})
    except stripe.error.StripeError as e:
        return Response({'detail': str(e)}, status=status.HTTP_502_BAD_GATEWAY)


@csrf_exempt
@api_view(['POST'])
@permission_classes([AllowAny])
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE', '')

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, settings.STRIPE_WEBHOOK_SECRET)
    except (ValueError, stripe.error.SignatureVerificationError):
        return Response({'detail': 'Invalid signature.'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        _handle_event(event)
    except Exception as e:
        return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    return Response({'status': 'ok'})


def _handle_event(event):
    event_type = event['type']
    data = event['data']['object']

    if event_type == 'checkout.session.completed':
        metadata = data.get('metadata', {})
        slug = metadata.get('tenant_slug')
        plan = metadata.get('plan')
        if slug and plan:
            try:
                tenant = Tenant.objects.get(slug=slug)
                tenant.plan = plan
                tenant.is_active = True
                tenant.stripe_subscription_id = data.get('subscription', '')
                tenant.save()
            except Tenant.DoesNotExist:
                pass

    elif event_type in ('customer.subscription.deleted',):
        sub_id = data.get('id')
        if sub_id:
            try:
                tenant = Tenant.objects.get(stripe_subscription_id=sub_id)
                tenant.plan = 'starter'
                tenant.is_active = False
                tenant.save()
            except Tenant.DoesNotExist:
                pass

    elif event_type == 'customer.subscription.updated':
        sub_id = data.get('id')
        sub_status = data.get('status')
        if sub_id and sub_status in ('active', 'trialing'):
            try:
                tenant = Tenant.objects.get(stripe_subscription_id=sub_id)
                tenant.is_active = True
                tenant.save()
            except Tenant.DoesNotExist:
                pass
