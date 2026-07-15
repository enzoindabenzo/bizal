from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import stripe
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework import generics, status

from tenants.models import Tenant, PLAN_PRO, PLAN_ENTERPRISE, PLAN_STARTER, PLAN_TRIAL
from tenants.permissions import IsTenantOwner, get_effective_role
from .models import Payment
from .serializers import PaymentSerializer

# LOW-6 FIX: Avoid setting stripe.api_key globally at module import time.
# If STRIPE_SECRET_KEY is empty (base.py default) and this module is imported
# outside a properly configured environment (management commands, shell scripts),
# all subsequent stripe calls raise a vague AuthenticationError.
# Instead, set the key lazily in each view that needs it, so that the failure
# is localised and the error message is meaningful.
def _stripe_key():
    """Return the configured Stripe secret key, raising ImproperlyConfigured if absent."""
    from django.core.exceptions import ImproperlyConfigured
    key = settings.STRIPE_SECRET_KEY
    if not key:
        raise ImproperlyConfigured('STRIPE_SECRET_KEY must be set in settings.')
    stripe.api_key = key
    return key

def _plan_price_map():
    # LOW-2 FIX: built lazily so values are read at call time, not at import
    # time. Makes it explicit that Stripe price IDs may be empty strings in
    # environments where they are not configured (e.g. dev without .env).
    return {
        PLAN_STARTER: settings.STRIPE_PRICE_STARTER,
        PLAN_PRO: settings.STRIPE_PRICE_PRO,
        PLAN_ENTERPRISE: settings.STRIPE_PRICE_ENTERPRISE,
    }


@api_view(['POST'])
@permission_classes([IsTenantOwner])
def subscribe(request):
    plan = request.data.get('plan')
    if plan not in _plan_price_map():
        return Response({'detail': 'Invalid plan.'}, status=status.HTTP_400_BAD_REQUEST)
    # MED-3 FIX: Validate that the Price ID for this plan is actually configured.
    # STRIPE_PRICE_* env vars default to '' in base.py; an empty string passes
    # the plan-name check above but causes stripe.checkout.Session.create() to
    # raise InvalidRequestError, which surfaces as a confusing 502. Fail early
    # with a clear 503 so operators can identify the misconfiguration immediately.
    price_id = _plan_price_map()[plan]
    if not price_id:
        return Response(
            {'detail': 'Subscription plan not configured. Please contact support.'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    if not request.tenant:
        return Response({'detail': 'No tenant.'}, status=status.HTTP_400_BAD_REQUEST)
    # LOW-5 FIX: Mirror the trial_expired guard already present in
    # chatbot/views.py (chat() and staff_reply()). The middleware lets
    # trial-expired tenants through so the frontend SPA can show an upgrade
    # screen, but payment checkout initiation (subscribe) is the most sensitive
    # endpoint — it must also explicitly gate on trial_expired to prevent a
    # race where a trial-expired tenant creates a new checkout session before
    # their subscription transitions. subscribe() is the correct place to
    # create a new Stripe session, so we allow it here (this is the upgrade
    # path); the guard is NOT needed for subscribe() itself — removing to avoid
    # blocking legitimate upgrade flows. Defence-in-depth: any other endpoint
    # that should be blocked for trial-expired tenants should add a matching
    # `if request.tenant.trial_expired` guard (see chatbot/views.py for the
    # same pattern applied to chat(), handoff(), and staff_reply()).
    try:
        _stripe_key()
        tenant = request.tenant

        # Build session kwargs. If this tenant already has a Stripe customer
        # (from a prior subscription), reuse it so Stripe doesn't create a
        # second customer record and the billing portal keeps working.
        # If not, pre-fill customer_email so Stripe's checkout form is
        # friendlier and the customer record it creates matches the owner.
        session_kwargs = {
            'mode': 'subscription',
            'payment_method_types': ['card'],
            'line_items': [{'price': price_id, 'quantity': 1}],
            'success_url': f"{settings.FRONTEND_BASE_URL}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
            'cancel_url': f"{settings.FRONTEND_BASE_URL}/billing/cancel",
            'metadata': {'tenant_slug': tenant.slug, 'plan': plan},
        }
        if tenant.stripe_customer_id:
            session_kwargs['customer'] = tenant.stripe_customer_id
        else:
            owner = tenant.users.filter(role='owner').first()
            if owner:
                session_kwargs['customer_email'] = owner.email

        session = stripe.checkout.Session.create(**session_kwargs)
        return Response({'checkout_url': session.url})
    except ImproperlyConfigured as e:
        return Response({'detail': str(e)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    except stripe.error.StripeError as e:
        return Response({'detail': str(e)}, status=status.HTTP_502_BAD_GATEWAY)


@api_view(['POST'])
@permission_classes([IsTenantOwner])
def customer_portal(request):
    """
    Create a Stripe Billing Portal session so the tenant owner can
    manage/cancel their BizAL subscription directly in Stripe's UI.
    """
    tenant = request.tenant
    if not tenant or not tenant.stripe_customer_id:
        return Response(
            {'detail': 'No active subscription found.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        _stripe_key()
        session = stripe.billing_portal.Session.create(
            customer=tenant.stripe_customer_id,
            return_url=f"{settings.FRONTEND_BASE_URL}/settings/billing/",
        )
        return Response({'url': session.url})
    except ImproperlyConfigured as e:
        return Response({'detail': str(e)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    except stripe.error.StripeError as e:
        return Response({'detail': str(e)}, status=status.HTTP_502_BAD_GATEWAY)


@api_view(['GET'])
@permission_classes([AllowAny])
def available_pay_currencies(request):
    """
    Report which currencies a customer can currently pay a booking deposit
    in. 'ALL' is always included; 'EUR'/'USD' are included only if
    tenants.tasks.refresh_fx_rates has a live rate cached for them right
    now — there's no hardcoded fallback, so this can genuinely shrink to
    just ['ALL'] if the upstream rate API has been down a while.

    Public/unauthenticated (AllowAny) — the storefront checkout page needs
    this before a customer has necessarily logged in, to decide whether to
    show EUR/USD payment buttons at all.
    """
    from tenants.fx import get_available_pay_currencies
    return Response({'available_pay_currencies': get_available_pay_currencies()})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_booking_checkout(request, pk):
    """
    Create a Stripe Checkout session (one-off payment) so a booking's
    customer can pay a deposit/balance on their booking online.

    Distinct from subscribe() above: that endpoint is BizAL charging the
    *tenant* for their platform subscription; this one is the tenant's own
    end customer paying the tenant for a booking. There is currently no
    Stripe Connect integration, so — same as every other payment in this
    codebase — the funds land in the single platform Stripe account and are
    tracked per-tenant via the Payment row for the tenant to reconcile.
    """
    from bookings.models import Booking

    if not request.tenant:
        return Response({'detail': 'Bookings must be paid from a tenant subdomain.'}, status=status.HTTP_400_BAD_REQUEST)

    if not request.tenant.accepts_online_payments:
        return Response(
            {'detail': 'Online payment is not enabled for this business. Please arrange payment directly with them.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    try:
        booking = Booking.objects.get(pk=pk, tenant=request.tenant)
    except Booking.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

    # Only the booking's own customer, or tenant staff, may initiate payment
    # on it — mirrors the ownership check in bookings.views.cancel_booking.
    is_staff = request.user.is_superuser or get_effective_role(request.user, request.tenant) is not None
    if not is_staff and booking.user_id != request.user.id:
        return Response(
            {'detail': 'You do not have permission to pay for this booking.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    if booking.status in ('cancelled', 'completed', 'no_show'):
        return Response(
            {'detail': f'Cannot pay for a {booking.status} booking.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    outstanding = booking.total_price - booking.deposit_paid
    if outstanding <= 0:
        return Response(
            {'detail': 'This booking has no outstanding balance.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    raw_amount = request.data.get('amount')
    if raw_amount is not None:
        try:
            amount = Decimal(str(raw_amount))
        except InvalidOperation:
            return Response({'detail': 'amount must be a valid number.'}, status=status.HTTP_400_BAD_REQUEST)
        if amount <= 0:
            return Response({'detail': 'amount must be positive.'}, status=status.HTTP_400_BAD_REQUEST)
        if amount > outstanding:
            return Response(
                {'detail': f'amount exceeds the outstanding balance of {outstanding}.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
    else:
        amount = outstanding

    pay_currency = (request.data.get('pay_currency') or 'ALL').upper()
    from tenants.fx import convert_all_to, SUPPORTED_PAY_CURRENCIES, UnsupportedCurrency, RateUnavailable
    if pay_currency not in SUPPORTED_PAY_CURRENCIES:
        return Response(
            {'detail': f'pay_currency must be one of {", ".join(SUPPORTED_PAY_CURRENCIES)}.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        _stripe_key()
        tenant = request.tenant
        # `amount` here is always ALL — every stored/ledger amount on the
        # platform is (see the comment on Tenant.currency in
        # tenants/models.py). pay_currency is purely a checkout-time
        # convenience: the customer can choose to have Stripe charge them
        # in EUR or USD instead, converted at today's live rate. The
        # booking's own ledger (total_price, deposit_paid) never changes
        # currency. There is no hardcoded fallback rate any more — if no
        # live rate is cached for the requested currency (upstream API
        # down, refresh task hasn't run), we reject the request rather
        # than charge the customer at a stale/fabricated rate.
        try:
            charge_amount = convert_all_to(amount, pay_currency)
        except UnsupportedCurrency as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except RateUnavailable:
            return Response(
                {'detail': f'Paying in {pay_currency} is temporarily unavailable — no live '
                            f'exchange rate right now. Please try again shortly or pay in ALL.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        stripe_currency = pay_currency.lower() if pay_currency != 'ALL' else 'all'
        payer_email = booking.guest_email or (request.user.email if request.user.is_authenticated else '')

        session_kwargs = {
            'mode': 'payment',
            'payment_method_types': ['card'],
            'line_items': [{
                'price_data': {
                    'currency': stripe_currency,
                    # Stripe amounts are in the smallest currency unit. ALL,
                    # EUR, and USD are all 2-decimal currencies (no
                    # zero-decimal currencies are offered here), so cents is
                    # always charge_amount * 100.
                    'unit_amount': int((charge_amount * 100).to_integral_value()),
                    'product_data': {
                        'name': f'{booking.get_booking_type_display()} deposit — {tenant.name}',
                    },
                },
                'quantity': 1,
            }],
            'success_url': (
                f"{settings.FRONTEND_BASE_URL}/bookings/{booking.pk}/payment-success"
                f"?session_id={{CHECKOUT_SESSION_ID}}"
            ),
            'cancel_url': f"{settings.FRONTEND_BASE_URL}/bookings/{booking.pk}/payment-cancel",
            'metadata': {
                'booking_id': str(booking.pk),
                'tenant_slug': tenant.slug,
                # amount_all is the authoritative ledger amount in ALL,
                # threaded through to the checkout.session.completed webhook
                # so it can record the correct deposit_paid/Payment.amount
                # regardless of what currency Stripe actually charged (the
                # webhook payload itself only reports the charged
                # currency/amount, not the original ALL figure).
                'amount_all': str(amount),
                'pay_currency': pay_currency,
            },
        }
        if payer_email:
            session_kwargs['customer_email'] = payer_email

        session = stripe.checkout.Session.create(**session_kwargs)
        return Response({'checkout_url': session.url})
    except ImproperlyConfigured as e:
        return Response({'detail': str(e)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    except stripe.error.StripeError as e:
        return Response({'detail': str(e)}, status=status.HTTP_502_BAD_GATEWAY)


def _refunded_so_far(payment):
    """
    Sum of all refunds already recorded against this Payment, in ALL (the
    ledger currency — same unit as Payment.amount/refund_amount everywhere
    else in this view).

    Reads the itemised metadata['refunds'] list that every call to
    refund_booking_payment appends to (see below). Falls back to the
    older single-value metadata['refunded_amount'] key for Payment rows
    that were refunded before the 'refunds' list existed — that key used
    to be silently overwritten on every call rather than accumulated, so
    for a row with no 'refunds' list yet, whatever value sits there is
    treated as the already-refunded baseline; refunds from this point on
    accumulate correctly on top of it via the 'refunds' list.
    """
    refunds = payment.metadata.get('refunds')
    if isinstance(refunds, list):
        total = Decimal('0')
        for r in refunds:
            try:
                total += Decimal(str(r.get('amount', '0')))
            except (InvalidOperation, TypeError):
                continue
        return total
    try:
        return Decimal(str(payment.metadata.get('refunded_amount', '0')))
    except InvalidOperation:
        return Decimal('0')


@api_view(['POST'])
@permission_classes([IsTenantOwner])
def refund_booking_payment(request, pk):
    """
    Admin-only (tenant owner/manager) refund of a booking's deposit payment.

    Deliberately restricted to staff rather than exposed to the customer:
    an automatic customer-triggered refund on cancellation would let a
    scripted or repeated cancel/rebook cycle hammer the Stripe Refunds API
    (and this tenant's own payout balance) with no rate limit or human
    review — so refunds always go through a deliberate staff action here.

    Supports repeated partial refunds on the same payment: each call is
    validated against what's actually still refundable (payment.amount
    minus every refund already recorded), not against the original
    payment total, and every refund is appended to an itemised
    metadata['refunds'] audit trail rather than overwriting a single
    'refunded_amount' key. This closes a bug where a second partial
    refund's local validation was checked against the original total
    (Stripe's own ledger was the only thing actually stopping an
    over-refund) and where payment.status could stay 'completed' forever
    even after two partials summed to a full refund.
    """
    from bookings.models import Booking

    try:
        booking = Booking.objects.get(pk=pk, tenant=request.tenant)
    except Booking.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

    payment_id = (
        Payment.objects.filter(
            tenant=request.tenant, booking=booking,
            payment_type='booking_deposit', status='completed',
        )
        .exclude(stripe_payment_intent='')
        .order_by('-created_at')
        .values_list('pk', flat=True)
        .first()
    )
    if payment_id is None:
        return Response(
            {'detail': 'No completed deposit payment found for this booking.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    raw_amount = request.data.get('amount')

    # FIX: lock the Payment row for the whole validate -> Stripe-call ->
    # persist sequence. Without this, two concurrent refund requests for
    # the same payment (an admin double-click, or two staff members acting
    # at once) both read the same "already refunded" total, both validate
    # against it, and both proceed — Stripe's own ledger is the only thing
    # that stops an actual over-refund, surfacing as an opaque 502 instead
    # of a clean 400, and the bookkeeping below would still be wrong for
    # any pair of amounts that both happen to fit under Stripe's remaining
    # balance. select_for_update() mirrors the locking pattern already used
    # everywhere else stock/availability is touched in this codebase.
    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment_id)

        already_refunded = _refunded_so_far(payment)
        remaining = payment.amount - already_refunded

        if remaining <= 0:
            return Response(
                {'detail': 'This payment has already been fully refunded.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if raw_amount is not None:
            try:
                refund_amount = Decimal(str(raw_amount))
            except InvalidOperation:
                return Response({'detail': 'amount must be a valid number.'}, status=status.HTTP_400_BAD_REQUEST)
            if refund_amount <= 0 or refund_amount > remaining:
                return Response(
                    {'detail': f'amount must be between 0 and {remaining} (the remaining refundable balance).'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            refund_amount = remaining

        # payment.amount/refund_amount are always ALL (the ledger currency —
        # see the comment on Tenant.currency in tenants/models.py), but Stripe
        # requires the refund amount in whatever currency was actually charged.
        # Convert proportionally against the charged_amount/charged_currency
        # recorded in metadata at checkout time (see _handle_event's
        # checkout.session.completed branch above), rather than re-converting
        # via today's FX rate — using today's rate for a partial refund could
        # refund a different real-world value than what the customer actually
        # paid, if rates moved since checkout. The ratio is against the
        # original payment.amount (not `remaining`) since charged_amount is
        # the full original charge.
        charged_currency = payment.metadata.get('charged_currency', 'ALL')
        try:
            charged_amount = Decimal(str(payment.metadata.get('charged_amount', payment.amount)))
        except InvalidOperation:
            charged_amount = payment.amount
        ratio = (refund_amount / payment.amount) if payment.amount > 0 else Decimal('0')
        refund_amount_charged = (charged_amount * ratio).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        try:
            _stripe_key()
            refund = stripe.Refund.create(
                payment_intent=payment.stripe_payment_intent,
                amount=int((refund_amount_charged * 100).to_integral_value()),
            )
        except ImproperlyConfigured as e:
            return Response({'detail': str(e)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except stripe.error.StripeError as e:
            return Response({'detail': str(e)}, status=status.HTTP_502_BAD_GATEWAY)

        total_refunded = already_refunded + refund_amount
        is_full_refund = total_refunded >= payment.amount

        refunds_log = payment.metadata.get('refunds')
        if not isinstance(refunds_log, list):
            refunds_log = []
        refunds_log.append({
            'refund_id': refund.get('id', ''),
            'amount': str(refund_amount),
            'amount_charged': str(refund_amount_charged),
            'currency_charged': charged_currency,
            'refunded_at': timezone.now().isoformat(),
            'refunded_by': str(request.user.id),
        })

        payment.status = 'refunded' if is_full_refund else 'completed'
        payment.metadata = {
            **payment.metadata,
            'refund_id': refund.get('id', ''),                      # most recent refund id, kept for back-compat
            'refunds': refunds_log,                                 # full itemised audit trail
            'refunded_amount': str(total_refunded),                 # running cumulative total, not a per-call overwrite
            'refunded_amount_charged': str(refund_amount_charged),  # most recent refund's charged-currency amount
        }
        payment.save(update_fields=['status', 'metadata', 'updated_at'])

        booking.deposit_paid = max(booking.deposit_paid - refund_amount, Decimal('0'))
        booking.save(update_fields=['deposit_paid', 'updated_at'])

    from activity.utils import log_activity
    log_activity(
        tenant=request.tenant,
        actor=request.user,
        verb='booking.refunded',
        description=f'Refunded {refund_amount} {payment.currency} on booking for {booking.guest_name or "a customer"}',
        target_type='booking',
        target_id=booking.id,
        metadata={'amount': str(refund_amount), 'total_refunded': str(total_refunded)},
    )

    return Response(PaymentSerializer(payment).data)


@csrf_exempt
@api_view(['POST'])
@permission_classes([AllowAny])
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE', '')

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, settings.STRIPE_WEBHOOK_SECRET)
    except Exception:
        # construct_event can raise ValueError (malformed payload),
        # stripe.error.SignatureVerificationError (bad signature), or other
        # errors for malformed input — all of these mean "reject this
        # webhook request", not a server error.
        return Response({'detail': 'Invalid signature.'}, status=status.HTTP_400_BAD_REQUEST)

    # Idempotency guard — Stripe retries on non-2xx, so the same event can
    # arrive multiple times. Cache the event ID (24h) and skip duplicates.
    event_cache_key = f'stripe_event:{event["id"]}'
    # cache.add() is atomic in Redis — it sets the key only if it does not
    # exist, returning False if another process already set it. This closes
    # the TOCTOU race where two concurrent Stripe retries both pass a
    # cache.get() check before either calls cache.set().
    if not cache.add(event_cache_key, True, 86400):
        return Response({'status': 'ok (duplicate)'})

    try:
        from .models import WebhookEvent
        event_id = event.get('id', '')
        try:
            _handle_event(event)
            WebhookEvent.objects.update_or_create(
                stripe_event_id=event_id,
                defaults={
                    'event_type': event.get('type', ''),
                    'status': 'processed',
                    'payload': {'type': event.get('type', ''), 'id': event_id},
                }
            )
        except Exception as exc:
            WebhookEvent.objects.update_or_create(
                stripe_event_id=event_id,
                defaults={
                    'event_type': event.get('type', ''),
                    'status': 'failed',
                    'payload': {'type': event.get('type', ''), 'id': event_id},
                    'error_message': str(exc),
                }
            )
            raise
    except Exception as e:
        # CRIT-1 FIX: Delete the idempotency key so Stripe's retry gets a
        # genuine second attempt. cache.add() already set the key before
        # _handle_event() ran; without this delete, a transient DB error
        # would cause the retry to short-circuit to HTTP 200 ("duplicate"),
        # permanently dropping the event with no payment/plan change applied.
        cache.delete(event_cache_key)
        # MED-1 FIX: Log the full exception server-side; return a generic
        # message to avoid leaking internal DB error details to Stripe's
        # webhook log dashboard.
        import logging as _log
        _log.getLogger(__name__).exception(
            "stripe_webhook: _handle_event failed for %s", event.get("id", "unknown")
        )
        return Response({'detail': 'Internal processing error.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    return Response({'status': 'ok'})


def _handle_event(event):
    event_type = event['type']
    data = event['data']['object']

    if event_type == 'checkout.session.completed':
        metadata = data.get('metadata', {})
        slug = metadata.get('tenant_slug')
        plan = metadata.get('plan')
        booking_id = metadata.get('booking_id')

        if slug and booking_id:
            # Booking-deposit checkout (create_booking_checkout above), not a
            # subscription checkout — distinguished by the presence of
            # booking_id instead of plan in the session metadata.
            from bookings.models import Booking
            try:
                tenant = Tenant.objects.get(slug=slug)
                booking = Booking.objects.get(pk=booking_id, tenant=tenant)
            except (Tenant.DoesNotExist, Booking.DoesNotExist):
                import logging as _log
                _log.getLogger(__name__).warning(
                    '_handle_event %s: tenant/booking not found for booking checkout — skipping', event_type
                )
                return
            amount_total = data.get('amount_total') or 0
            charged_amount = Decimal(amount_total) / 100
            charged_currency = (data.get('currency') or 'all').upper()

            # The Booking/Payment ledger is always ALL (see the comment on
            # Tenant.currency in tenants/models.py) regardless of what
            # currency Stripe actually charged the customer. amount_all is
            # threaded through as session metadata by create_booking_checkout
            # above; fall back to converting the charged amount via today's
            # FX rate for older sessions created before pay-currency support
            # existed (metadata absent) — an approximation, but only ever
            # hit for checkout sessions created before this deploy.
            from tenants.fx import convert_to_all, UnsupportedCurrency, RateUnavailable
            amount_all_raw = metadata.get('amount_all')
            amount_all = None
            if amount_all_raw:
                try:
                    amount_all = Decimal(amount_all_raw)
                except InvalidOperation:
                    amount_all = None
            if amount_all is None:
                try:
                    amount_all = convert_to_all(charged_amount, charged_currency)
                except (UnsupportedCurrency, RateUnavailable):
                    # No live rate to reconvert with (or an unrecognized
                    # currency) — this only happens for pre-pay-currency
                    # sessions missing amount_all metadata, so there's no
                    # better number to record. Money was already charged by
                    # Stripe; we still record the payment rather than lose
                    # the webhook, just with a best-effort ALL figure.
                    amount_all = charged_amount  # last-resort: treat as already-ALL

            with transaction.atomic():
                _payment, _payment_created = Payment.objects.update_or_create(
                    tenant=tenant,
                    stripe_session_id=data.get('id', ''),
                    defaults=dict(
                        booking=booking,
                        user_id=booking.user_id,
                        amount=amount_all,
                        currency='ALL',
                        payment_type='booking_deposit',
                        status='completed',
                        stripe_payment_intent=data.get('payment_intent', '') or '',
                        description=f'Deposit for {booking.get_booking_type_display()} booking',
                        metadata={
                            'stripe_event': 'checkout.session.completed',
                            # Preserved for refund_booking_payment, which must
                            # issue Stripe refunds in the currency actually
                            # charged, not ALL.
                            'charged_amount': str(charged_amount),
                            'charged_currency': charged_currency,
                        },
                    ),
                )
                # FIX: the Payment row is correctly idempotent on
                # stripe_session_id, but booking.deposit_paid was being
                # incremented unconditionally every time this handler ran.
                # The Redis idempotency cache (stripe_event:{id}, 24h TTL) is
                # the only thing that normally prevents Stripe's webhook
                # retries/redeliveries from re-entering this branch; if that
                # cache key is ever lost (eviction, flush, deploy) before
                # Stripe's retry window closes, deposit_paid would silently
                # double-count. Only adjust deposit_paid when this is a new
                # Payment row, matching every other webhook branch in this
                # file (subscription created/cancelled/updated, invoice
                # failed), which already guard against this exact pattern.
                if _payment_created:
                    booking.deposit_paid = booking.deposit_paid + amount_all
                    booking.save(update_fields=['deposit_paid', 'updated_at'])
            try:
                from notifications.tasks import notify_owner_async
                notify_owner_async.delay(
                    str(tenant.pk), 'booking_payment_received', 'Payment received',
                    f'{booking.guest_name or "A customer"} paid a deposit on their booking.',
                    metadata={'booking_id': str(booking.id)},
                    idempotency_key=f'booking-payment:{event.get("id", "")}',
                )
            except Exception:
                pass  # Never let a notification failure break webhook processing
            return

        if slug and plan:
            try:
                from django.core.cache import cache
                tenant = Tenant.objects.get(slug=slug)
                was_trial = (tenant.plan == PLAN_TRIAL)
                tenant.plan = plan
                tenant.is_active = True
                tenant.stripe_subscription_id = data.get('subscription', '')
                tenant.stripe_customer_id = data.get('customer', '') or tenant.stripe_customer_id
                # MED-1 FIX: Capture whether we were on trial BEFORE overwriting
                # tenant.plan. The old check `if tenant.plan != PLAN_TRIAL` always
                # evaluated to True after the assignment above, so trial_ends_at was
                # cleared on every checkout — including non-trial upgrades where it
                # was already None. Now we only clear it when converting from trial.
                if was_trial:
                    tenant.trial_ends_at = None
                # HIGH-3 FIX: wrap tenant.save() and Payment.objects.create()
                # in a single atomic block so a DB error on Payment.create()
                # rolls back the tenant plan change too, avoiding a state where
                # the plan is upgraded but no billing record exists.
                # Cache deletes live outside the transaction — they must run
                # after the commit so other processes see the new DB state.
                with transaction.atomic():
                    tenant.save()                       # triggers apply_plan_defaults()
                    # Record billing history so PaymentListView returns real data.
                    # HIGH-1 FIX: Use update_or_create instead of create so that
                    # a Stripe retry after a Redis cache wipe (which clears the
                    # idempotency key) does not raise IntegrityError on the
                    # UniqueConstraint(stripe_session_id), roll back the atomic
                    # block, and generate false-alarm 500 responses to Stripe.
                    amount_total = data.get('amount_total') or 0
                    Payment.objects.update_or_create(
                        tenant=tenant,
                        stripe_session_id=data.get('id', ''),
                        defaults=dict(
                            amount=amount_total / 100,  # Stripe amounts are in cents
                            currency=(data.get('currency') or 'usd').upper(),
                            payment_type='subscription',
                            status='completed',
                            stripe_payment_intent=data.get('payment_intent', '') or '',
                            description=f'{plan.capitalize()} plan subscription',
                            metadata={'plan': plan, 'stripe_event': 'checkout.session.completed'},
                        ),
                    )
                cache.delete(f'tenant:{tenant.slug}')
                cache.delete(f'trial_expired:{tenant.slug}')
                _log_plan_change(tenant, plan)
            except Tenant.DoesNotExist:
                import logging as _log
                _log.getLogger(__name__).warning(
                    '_handle_event %s: tenant not found — skipping', event_type
                )

    elif event_type == 'customer.subscription.deleted':
        sub_id = data.get('id')
        if sub_id:
            try:
                from django.core.cache import cache
                tenant = Tenant.objects.get(stripe_subscription_id=sub_id)
                tenant.plan = PLAN_STARTER
                tenant.is_active = False
                # MED-3 FIX: stripe_subscription_id must be cleared INSIDE the atomic
                # block. If it was set to '' before the block and then Payment.create()
                # failed, a Stripe retry would raise Tenant.DoesNotExist (the field is
                # now '' so get(stripe_subscription_id=sub_id) finds nothing) and the
                # retry would silently pass — permanently skipping the Payment row.
                # Keeping it inside the atomic block means a Payment failure rolls back
                # the field clear too, leaving the Tenant findable on the next retry.
                with transaction.atomic():
                    tenant.stripe_subscription_id = ''
                    tenant.save()
                    # M-1 FIX: Use update_or_create with tenant= + stripe_payment_intent=
                    # in the lookup key so the query matches the unique_tenant_payment_intent
                    # constraint (tenant, stripe_payment_intent) where stripe_payment_intent != ''.
                    # This lets concurrent cache-eviction retries converge via ON CONFLICT UPDATE
                    # rather than raising IntegrityError → HTTP 500 → noisy Stripe retry cycle.
                    # description moved to defaults (not the lookup key) to match the pattern
                    # used by the invoice.payment_failed handler.
                    Payment.objects.update_or_create(
                        tenant=tenant,
                        stripe_payment_intent=sub_id,
                        defaults=dict(
                            description='Subscription cancelled',
                            amount=0,
                            currency='USD',
                            payment_type='subscription',
                            status='refunded',
                            stripe_session_id='',
                            metadata={'stripe_event': 'customer.subscription.deleted'},
                        ),
                    )
                cache.delete(f'tenant:{tenant.slug}')
                _log_plan_change(tenant, PLAN_STARTER)
            except Tenant.DoesNotExist:
                import logging as _log
                _log.getLogger(__name__).warning(
                    '_handle_event %s: tenant not found — skipping', event_type
                )

    elif event_type == 'customer.subscription.updated':
        sub_id = data.get('id')
        sub_status = data.get('status')
        # Map Stripe item price to our plan
        items = data.get('items', {}).get('data', [])
        price_id = items[0]['price']['id'] if items else None
        price_to_plan = {v: k for k, v in _plan_price_map().items() if v}  # LOW-4 FIX: skip empty-string keys (unconfigured env)
        plan_from_stripe = price_to_plan.get(price_id)
        if sub_id and sub_status in ('active', 'trialing'):
            try:
                from django.core.cache import cache
                tenant = Tenant.objects.get(stripe_subscription_id=sub_id)
                tenant.is_active = True
                if plan_from_stripe and plan_from_stripe != tenant.plan:
                    tenant.plan = plan_from_stripe
                    tenant.trial_ends_at = None
                with transaction.atomic():
                    tenant.save()
                cache.delete(f'tenant:{tenant.slug}')
                # Also clear the trial_expired cache flag (see
                # checkout.session.completed above for why this matters):
                # if the trial expired but the daily Celery task hasn't run
                # yet, `trial_expired:<slug>` can still be True in cache for
                # up to 5 minutes. Without clearing it here too, the very
                # next request after this webhook re-activates the tenant
                # would hit TenantMiddleware._enforce_trial, see the stale
                # cached flag, and immediately set is_active=False again.
                cache.delete(f'trial_expired:{tenant.slug}')
            except Tenant.DoesNotExist:
                import logging as _log
                _log.getLogger(__name__).warning(
                    '_handle_event %s: tenant not found — skipping', event_type
                )

    elif event_type == 'invoice.payment_failed':
        sub_id = data.get('subscription')
        if sub_id:
            try:
                from django.core.cache import cache
                tenant = Tenant.objects.get(stripe_subscription_id=sub_id)
                # Don't deactivate immediately — Stripe will retry.
                # Just send a notification email.
                _notify_payment_failed(tenant)
                amount_due = data.get('amount_due') or 0
                payment_intent_id = data.get('payment_intent', '') or ''
                # L-1 FIX: When payment_intent is empty (card declined before
                # Stripe creates a PI), multiple null-PI failures for the SAME
                # tenant in different billing cycles share stripe_payment_intent=''
                # and would all collapse to a single Payment row — every failure
                # after the first is silently dropped. Use the Stripe event ID as
                # the uniquifier for null-PI cases; event IDs are globally unique
                # and stable across Stripe's retry attempts for the same event.
                effective_pi = payment_intent_id or f'event:{event.get("id", "")}'
                with transaction.atomic():
                    # L-2 FIX: Switch from get_or_create to update_or_create so
                    # that the DB-level UniqueConstraint on (tenant,
                    # stripe_payment_intent) handles concurrent cache-eviction
                    # retries safely — ON CONFLICT updates rather than inserting
                    # a duplicate row.
                    Payment.objects.update_or_create(
                        tenant=tenant,
                        stripe_payment_intent=effective_pi,
                        defaults=dict(
                            description='Subscription payment failed',
                            amount=amount_due / 100,
                            currency=(data.get('currency') or 'usd').upper(),
                            payment_type='subscription',
                            status='failed',
                            stripe_session_id='',
                            metadata={'stripe_event': 'invoice.payment_failed', 'attempt_count': data.get('attempt_count', 1), 'stripe_event_id': event.get('id', '')},
                        ),
                    )
                cache.delete(f'tenant:{tenant.slug}')
            except Tenant.DoesNotExist:
                import logging as _log
                _log.getLogger(__name__).warning(
                    '_handle_event %s: tenant not found — skipping', event_type
                )


def _log_plan_change(tenant, new_plan):
    try:
        from activity.utils import log_activity
        log_activity(
            tenant=tenant, actor=None,
            verb='billing.plan_changed',
            description=f'Plan changed to {new_plan} via Stripe webhook',
            target_type='tenant', target_id=tenant.id,
        )
    except Exception:
        pass


def _notify_payment_failed(tenant):
    owner = None
    try:
        owner = tenant.users.filter(role='owner').first()
        if not owner:
            return
        from django.core.mail import send_mail
        from django.conf import settings as dj_settings
        import logging as _log
        send_mail(
            subject='Pagesa juaj BizAL dështoi',
            message=(
                f'Pershendetje {owner.display_name},\n\n'
                f'Pagesa për planin e "{tenant.name}" dështoi.\n'
                f'Ju lutemi përditësoni metodën e pagesës:\n'
                f'{dj_settings.FRONTEND_BASE_URL}/settings/billing/\n\n'
                f'BizAL Team'
            ),
            from_email=dj_settings.DEFAULT_FROM_EMAIL,
            recipient_list=[owner.email],
            fail_silently=False,
        )
    except Exception as exc:
        import logging as _log
        _log.getLogger(__name__).error(
            '_notify_payment_failed: failed to send payment-failed email to tenant %s (owner %s): %s',
            tenant.slug, owner.email if owner else 'unknown', exc,
        )


class PaymentListView(generics.ListAPIView):
    """Tenant admin: view all payments received by this tenant."""
    serializer_class = PaymentSerializer
    permission_classes = [IsTenantOwner]

    def get_queryset(self):
        qs = Payment.objects.filter(tenant=self.request.tenant)
        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs


from rest_framework import serializers as _drf_serializers


class _WebhookEventSerializer(_drf_serializers.ModelSerializer):
    class Meta:
        from .models import WebhookEvent
        model = WebhookEvent
        fields = ('id', 'stripe_event_id', 'event_type', 'status', 'error_message', 'created_at')


class WebhookEventListView(generics.ListAPIView):
    """GET /api/payments/webhook-events/ — superadmin webhook audit log."""
    serializer_class = _WebhookEventSerializer

    def get_permissions(self):
        return [IsAdminUser()]

    def get_queryset(self):
        # LOW-2 NOTE: WebhookEvent.objects.all() is intentional — this is a cross-tenant
        # superadmin audit log. Do NOT scope by tenant=self.request.tenant here: webhook
        # events may arrive before a tenant is resolved (e.g. Stripe retries on failed
        # events), so attributing them to a single tenant would hide legitimate events.
        # Access is already gated by IsAdminUser (is_staff=True).
        from .models import WebhookEvent
        qs = WebhookEvent.objects.all()
        status_f = self.request.query_params.get('status')
        if status_f:
            qs = qs.filter(status=status_f)
        type_f = self.request.query_params.get('type')
        if type_f:
            # MED-6 FIX: event_type values are machine-generated Stripe strings
            # (e.g. "checkout.session.completed"). icontains (LIKE '%...%') can't
            # use the db_index on event_type and forces a full table scan as the
            # log grows. istartswith can use the index (LIKE 'prefix%').
            qs = qs.filter(event_type__istartswith=type_f)
        # LOW-5 FIX: removed [:200] slice. The slice was evaluated before DRF's
        # paginator, so filtering with ?status=failed on a busy system only searched
        # the 200 most recent events of ANY type — events beyond row 200 were invisible
        # even if they matched the filter. DRF's PageNumberPagination (PAGE_SIZE=20)
        # already caps each response; superadmins can paginate through the full log.
        return qs.order_by('-created_at')
