from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
from django.db.models import Q
from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from bizal.ratelimit_utils import ratelimit_decorator as _ratelimit_decorator
import logging

logger = logging.getLogger(__name__)

from .models import Tenant, TenantLocation, TenantReferral, PLAN_TRIAL, TRIAL_DAYS
from .serializers import (
    TenantPublicSerializer, TenantSettingsSerializer,
    TenantSignupSerializer, MarketplaceTenantSerializer,
    TenantLocationSerializer, TenantLocationCreateSerializer, TenantReferralSerializer,
    CreditLedgerSerializer,
)
from .permissions import IsTenantOwner, MainDomainOnly, IsOwnTenantStaff, IsOwnTenantOwnerOrManager
from bizal.throttles import PublicReadThrottle
from accounts.models import User
from django.utils import timezone
import datetime


# ── Public info ───────────────────────────────────────────────────────────────

class TenantInfoView(generics.RetrieveAPIView):
    serializer_class = TenantPublicSerializer
    permission_classes = [AllowAny]
    throttle_classes = [PublicReadThrottle]

    def get_object(self):
        if self.request.tenant:
            return self.request.tenant
        slug = self.request.query_params.get('slug')
        if slug:
            try:
                # MEDIUM-3 FIX: Previously returned full public tenant info for
                # ANY slug including inactive/pending/deactivated tenants — bypassing
                # the middleware guard that returns 404 for inactive tenants on
                # their subdomain. Now filter to is_active=True so deactivated
                # tenants cannot be scraped via the ?slug= query param.
                # Trial-expired tenants ARE still served (middleware allows them
                # through) — only inactive/pending ones are blocked.
                return Tenant.objects.prefetch_related('features', 'locations').get(
                    slug=slug, is_active=True
                )
            except Tenant.DoesNotExist:
                pass
        # LOW-5 FIX (v36): log when no tenant can be resolved so frontend bugs
        # that omit the ?slug= param are visible in logs rather than silently
        # returning 404 — at scale this distinguishes intentional main-domain
        # calls from broken frontend behaviour.
        logger.debug(
            'TenantInfoView: no tenant resolved (tenant=%r, slug=%r, path=%s)',
            getattr(self.request, 'tenant', None),
            slug,
            self.request.path,
        )
        return None

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance is None:
            return Response({'detail': 'Tenant not found.'}, status=404)
        serializer = self.get_serializer(instance)
        return Response(serializer.data)


# ── Tenant owner settings ─────────────────────────────────────────────────────

class TenantSettingsView(generics.RetrieveUpdateAPIView):
    serializer_class = TenantSettingsSerializer
    permission_classes = [IsTenantOwner]

    def get_object(self):
        return self.request.tenant

    def perform_update(self, serializer):
        serializer.save()
        cache.delete(f'tenant:{self.request.tenant.slug}')


class TenantMeView(generics.RetrieveUpdateAPIView):
    """
    GET/PATCH the tenant the requesting user belongs to (via user.tenant,
    not request.tenant — this works regardless of which domain the request
    came in on).

    NOTE: previously this only required IsAuthenticated, which meant any
    authenticated user with a tenant FK — including a plain customer, who
    is_authenticated and has a tenant just like an owner does — could PATCH
    this endpoint and rewrite their tenant's name/branding/business_hours/
    marketplace listing etc. Read access stays open to any staff-level
    user of the tenant (owner/manager/staff); write is owner/manager only.
    """
    serializer_class = TenantSettingsSerializer

    def get_permissions(self):
        if self.request.method in ('PUT', 'PATCH'):
            return [IsOwnTenantOwnerOrManager()]
        return [IsOwnTenantStaff()]

    def get_object(self):
        tenant = getattr(self.request.user, 'tenant', None)
        if tenant is None:
            from rest_framework.exceptions import NotFound
            raise NotFound('No tenant associated with this account.')
        return tenant

    def perform_update(self, serializer):
        serializer.save()
        cache.delete(f'tenant:{serializer.instance.slug}')


@api_view(['POST'])
@permission_classes([IsOwnTenantOwnerOrManager])
def change_plan(request):
    """
    Self-service plan upgrade/downgrade — switches the tenant's own plan
    directly, without going through Stripe checkout. This exists alongside
    /payments/subscribe/ (which starts a real Stripe subscription) so a
    tenant owner can still change plans when Stripe isn't configured, and
    can freely downgrade (Stripe checkout only ever moves a tenant up to
    a paid plan, never back down).
    """
    from .models import PLAN_STARTER, PLAN_PRO, PLAN_ENTERPRISE

    tenant = getattr(request.user, 'tenant', None)
    if tenant is None:
        return Response({'detail': 'No tenant associated with this account.'}, status=status.HTTP_400_BAD_REQUEST)

    new_plan = request.data.get('plan')
    valid_plans = {PLAN_STARTER, PLAN_PRO, PLAN_ENTERPRISE}
    if new_plan not in valid_plans:
        return Response(
            {'detail': f'Invalid plan. Choices: {sorted(valid_plans)}'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if new_plan == tenant.plan:
        return Response(TenantSettingsSerializer(tenant).data)

    tenant.plan = new_plan
    tenant.save(update_fields=['plan'])  # Tenant.save() re-applies plan defaults (features/limits)
    cache.delete(f'tenant:{tenant.slug}')

    return Response(TenantSettingsSerializer(tenant).data)


# ── Signup ────────────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([AllowAny, MainDomainOnly])
@_ratelimit_decorator('3/h')
def tenant_signup(request):
    serializer = TenantSignupSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    d = serializer.validated_data

    referrer = None
    ref_code = d.get('referral_code', '').strip()
    if ref_code:
        try:
            referrer = Tenant.objects.get(referral_code=ref_code)
        except Tenant.DoesNotExist:
            pass

    # FIX: Wrap all DB writes in a single atomic block so that if
    # User.objects.create_user() raises IntegrityError (duplicate email
    # TOCTOU race), the entire transaction — Tenant row, TenantReferral row,
    # AND the referral credit F() update + CreditLedger entry — are all
    # rolled back together. The previous manual `tenant.delete()` approach
    # correctly removed the Tenant (via CASCADE to TenantReferral) but left
    # the referrer's `referral_credits` balance incremented and a stale
    # CreditLedger row behind because those writes had already committed.
    from django.db import IntegrityError, transaction
    try:
        with transaction.atomic():
            # trial_ends_at is NOT set here — it is set when the superadmin activates
            # the tenant (is_active False → True) via /django-admin/, in
            # tenants/admin.py::apply_activation_side_effects().
            # Until activation, trial_ends_at is None and the 14-day clock has not started.
            tenant = Tenant.objects.create(
                name=d['business_name'],
                slug=d['slug'],
                business_type=d['business_type'],
                is_active=False,
                # Tenant picks their own plan on the signup form now. Falls
                # back to the trial when omitted (matches the serializer's
                # own default), so old clients that never send `plan` still
                # behave exactly as before.
                plan=d.get('plan', PLAN_TRIAL),
                referred_by=referrer,
            )

            # Record referral and award credit inside the same transaction so
            # a failed user creation rolls back the credit increment atomically.
            if referrer:
                ref = TenantReferral.objects.create(referrer=referrer, referred=tenant)
                ref.apply_credit()

            # Guard against the TOCTOU race between validate_owner_email() and
            # here: two simultaneous signups with the same email can both pass
            # the .exists() check in the serializer before either creates the
            # User row. Catching IntegrityError inside atomic() ensures full
            # rollback of all writes above including the referral credit.
            user = User.objects.create_user(
                email=d['owner_email'],
                password=d['owner_password'],
                full_name=d['owner_name'],
                tenant=tenant,
                role='owner',
            )
    except IntegrityError:
        return Response(
            {'owner_email': ['An account with this email already exists.']},
            status=status.HTTP_400_BAD_REQUEST,
        )

    refresh = RefreshToken.for_user(user)

    # Notify the owner their account is pending review.
    # Done synchronously — it's a single send on an infrequent path and
    # doesn't need to block the response meaningfully.
    try:
        send_mail(
            subject='Llogaria juaj BizAL është në shqyrtim',
            message=(
                f'Përshëndetje {user.full_name},\n\n'
                f'Faleminderit që u regjistruat në BizAL!\n\n'
                f'Llogaria për "{tenant.name}" është krijuar dhe po shqyrtohet nga ekipi ynë. '
                f'Do t\'ju njoftojmë me email sapo të aktivizohet — zakonisht brenda 24 orësh.\n\n'
                f'Nëse keni pyetje, shkruani te support@bizal.al\n\n'
                f'BizAL Team'
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=True,
        )
        # Internal alert so superadmin e di pa hapur panelin.
        send_mail(
            subject=f'[BizAL] Tenant i ri në pritje: {tenant.name}',
            message=(
                f'Tenant i ri u regjistrua dhe pret aktivizim.\n\n'
                f'Emri: {tenant.name}\n'
                f'Slug: {tenant.slug}\n'
                f'Lloji: {tenant.business_type}\n'
                f'Owner: {user.full_name} <{user.email}>\n\n'
                f'Aktivizo nga paneli i superadmin-it.'
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[settings.ADMIN_EMAIL],
            fail_silently=True,
        )
    except Exception:
        pass  # Email dërgimi nuk duhet të thyejë signup-in

    return Response({
        'message': f'Tenant created. Your {TRIAL_DAYS}-day trial will start once your account is activated.',
        'status': 'pending_activation',  # LOW-5 FIX: signal to frontend that tokens are not immediately usable
        'slug': tenant.slug,
        'referral_code': tenant.referral_code,
        'trial_ends_at': tenant.trial_ends_at,
        'user_id': str(user.id),
        'access': str(refresh.access_token),
        'refresh': str(refresh),
    }, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_tenant(request):
    """
    Create a tenant for an already-authenticated user who has no tenant yet.
    Used by the onboarding flow when the user registered first then wants to open a business.
    """
    user = request.user
    if getattr(user, 'tenant', None) is not None:
        return Response({'detail': 'You already have a business.'}, status=status.HTTP_400_BAD_REQUEST)

    from .models import PLAN_STARTER, PLAN_PRO, PLAN_ENTERPRISE

    business_name = request.data.get('business_name', '').strip()
    slug = request.data.get('slug', '').strip()
    business_type = request.data.get('business_type', '').strip()
    # Optional — lets the tenant pick their own plan when creating the
    # business (same options offered on the signup form). Defaults to the
    # 14-day trial when not sent, so existing callers keep working as before.
    plan = request.data.get('plan', PLAN_TRIAL).strip()
    valid_plans = {PLAN_TRIAL, PLAN_STARTER, PLAN_PRO, PLAN_ENTERPRISE}
    if plan not in valid_plans:
        return Response(
            {'plan': [f'Invalid plan. Choices: {sorted(valid_plans)}']},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if not business_name or not slug or not business_type:
        return Response({'detail': 'business_name, slug and business_type are required.'}, status=status.HTTP_400_BAD_REQUEST)

    if Tenant.objects.filter(slug=slug).exists():
        return Response({'slug': ['This slug is already taken.']}, status=status.HTTP_400_BAD_REQUEST)

    from django.db import transaction
    with transaction.atomic():
        tenant = Tenant.objects.create(
            name=business_name,
            slug=slug,
            business_type=business_type,
            is_active=False,
            plan=plan,
        )
        user.tenant = tenant
        user.role = 'owner'
        user.save(update_fields=['tenant', 'role'])

    refresh = RefreshToken.for_user(user)
    return Response({
        'access': str(refresh.access_token),
        'refresh': str(refresh),
        'slug': slug,
    }, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([AllowAny])
@_ratelimit_decorator('10/m', method='GET')
def check_slug(request):
    """
    Public, unauthenticated slug-availability check used during onboarding.
    Rate-limited per IP — without this, anyone could enumerate every taken
    slug (= business name) on the platform by brute-forcing characters,
    which leaks which business names are registered.
    FIX (M-2): tightened from 30/m to 10/m to make systematic enumeration
    across IP rotation meaningfully slower without impacting real users
    (onboarding wizard checks slug on-type, rarely more than ~5/minute).
    v66 FIX (LOW): Also reject reserved slugs (admin, api, health, etc.).
    TenantSignupSerializer already blocks these at submit time, so this was
    never a security gap — but without this check the wizard showed a false
    "available" green indicator for a reserved slug, only to have the actual
    signup fail. Checking Tenant._RESERVED_SLUGS here keeps the on-type
    preview consistent with the real validation outcome.
    """
    slug = request.query_params.get('slug', '')
    available = (
        slug not in Tenant._RESERVED_SLUGS
        and not Tenant.objects.filter(slug=slug).exists()
    )
    return Response({'slug': slug, 'available': available})


@api_view(['GET'])
@permission_classes([AllowAny])
def business_types(request):
    from django.db.models import Count
    from .business_type_meta import business_types_payload

    counts = dict(
        Tenant.objects.filter(is_active=True, listed_on_marketplace=True)
        .values_list('business_type')
        .annotate(n=Count('id'))
    )
    return Response({'results': business_types_payload(counts)})


# ── Marketplace directory ─────────────────────────────────────────────────────

from rest_framework.pagination import PageNumberPagination


class MarketplacePagination(PageNumberPagination):
    page_size = 30
    page_size_query_param = 'page_size'
    max_page_size = 100


@api_view(['GET'])
@permission_classes([AllowAny])
def marketplace_list(request):
    """
    Public discovery endpoint.
    Query params:
      ?type=restaurant   — filter by business_type
      ?city=Tirane       — filter by city (case-insensitive)
      ?q=text            — search name / tagline
      ?page=2            — pagination (30 per page, max 100 via page_size=)
    """
    qs = Tenant.objects.filter(is_active=True, listed_on_marketplace=True)

    btype = request.query_params.get('type', '').strip()
    if btype:
        qs = qs.filter(business_type=btype)

    city = request.query_params.get('city', '').strip()
    if city:
        qs = qs.filter(city__icontains=city)

    q = request.query_params.get('q', '').strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(tagline__icontains=q) | Q(marketplace_description__icontains=q))

    paginator = MarketplacePagination()
    page = paginator.paginate_queryset(qs.order_by('name'), request)
    serializer = MarketplaceTenantSerializer(page, many=True, context={'request': request})
    return paginator.get_paginated_response(serializer.data)


# ── Locations (multi-branch) ──────────────────────────────────────────────────

class TenantLocationListView(generics.ListCreateAPIView):
    permission_classes = [IsTenantOwner]

    def get_queryset(self):
        return TenantLocation.objects.filter(tenant=self.request.tenant)

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return TenantLocationCreateSerializer
        return TenantLocationSerializer

    def perform_create(self, serializer):
        if not self.request.tenant.has_feature('multi_location'):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('Multi-location requires Enterprise plan.')
        serializer.save(tenant=self.request.tenant)


class TenantLocationDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = TenantLocationSerializer
    permission_classes = [IsTenantOwner]

    def get_queryset(self):
        return TenantLocation.objects.filter(tenant=self.request.tenant)


# ── Referrals ─────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_referrals(request):
    tenant = getattr(request.user, 'tenant', None)
    if not tenant:
        return Response({'detail': 'No tenant.'}, status=404)
    records = TenantReferral.objects.filter(referrer=tenant).select_related('referred')
    serializer = TenantReferralSerializer(records, many=True)
    return Response({
        'referral_code': tenant.referral_code,
        'total_credits': str(tenant.referral_credits),
        'referrals': serializer.data,
    })



# ── Credits ───────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsTenantOwner])
def credit_balance(request):
    """
    GET /api/tenants/credits/balance/
    Returns the current credit balance and last 10 ledger entries for quick display.
    """
    from .models import CreditLedger
    tenant = request.tenant
    if not tenant:
        return Response({'detail': 'No tenant.'}, status=status.HTTP_400_BAD_REQUEST)
    entries = CreditLedger.objects.filter(tenant=tenant).order_by('-created_at')[:10]
    return Response({
        'balance': str(tenant.referral_credits),
        'recent': CreditLedgerSerializer(entries, many=True).data,
    })


@api_view(['GET'])
@permission_classes([IsTenantOwner])
def credit_ledger(request):
    """
    GET /api/tenants/credits/ledger/
    Full paginated ledger history for the tenant.
    """
    from .models import CreditLedger
    from rest_framework.pagination import PageNumberPagination

    tenant = request.tenant
    if not tenant:
        return Response({'detail': 'No tenant.'}, status=status.HTTP_400_BAD_REQUEST)

    qs = CreditLedger.objects.filter(tenant=tenant).order_by('-created_at')  # HIGH-2 FIX
    paginator = PageNumberPagination()
    paginator.page_size = 50
    page = paginator.paginate_queryset(qs, request)
    items = page if page is not None else qs
    # FIX: CreditLedgerSerializer is a proper ModelSerializer — use .data,
    # not the old hand-rolled to_dict() class-method that no longer exists.
    data = CreditLedgerSerializer(items, many=True).data
    if page is not None:
        return paginator.get_paginated_response(data)
    return Response(data)


@api_view(['POST'])
@permission_classes([IsTenantOwner])
def credit_redeem(request):
    """
    POST /api/tenants/credits/redeem/
    Body: { "amount": "5.00", "invoice_id": "<uuid>", "description": "..." }

    Atomically debits credits from the tenant's balance and, if invoice_id is
    provided, actually applies the credit to that invoice: the amount applied
    is capped at the invoice's current total_amount (you can't redeem more
    credit than the invoice is worth), and a negative InvoiceLine is added so
    Invoice.recompute_total() reflects the reduced balance owed. Returns the
    updated credit balance plus the amount requested vs. actually applied.

    Note: referral credits, like every other stored amount on the platform,
    are denominated in ALL (Lek) — see fx.py's module docstring. The old
    credit_eur / total_credits_eur field and response-key names have been
    renamed to credit_amount / total_credits to reflect that; there was
    never an actual EUR value to convert, and no tenants.fx conversion
    belongs here.
    """
    from decimal import Decimal, InvalidOperation
    from django.db import transaction
    from .models import CreditLedger

    tenant = request.tenant
    if not tenant:
        return Response({'detail': 'No tenant.'}, status=status.HTTP_400_BAD_REQUEST)

    raw_amount = request.data.get('amount')
    invoice_id = request.data.get('invoice_id')
    description = request.data.get('description', '')

    try:
        amount = Decimal(str(raw_amount))
    except (InvalidOperation, TypeError):
        return Response({'detail': 'Invalid amount.'}, status=status.HTTP_400_BAD_REQUEST)

    if amount <= 0:
        return Response({'detail': 'Amount must be positive.'}, status=status.HTTP_400_BAD_REQUEST)

    if invoice_id and not description:
        description = f'Applied to invoice {invoice_id}'

    # If an invoice_id was supplied, verify it belongs to this tenant before
    # touching the balance — prevents cross-tenant credit theft.
    invoice = None
    if invoice_id:
        try:
            from billing.models import Invoice
            invoice = Invoice.objects.get(pk=invoice_id, tenant=tenant)
        except Exception:
            return Response({'detail': 'Invoice not found.'}, status=status.HTTP_404_NOT_FOUND)

    # Cap what's actually applied at the invoice's remaining balance — the
    # tenant can request more than the invoice is worth, but we only ever
    # spend and apply the smaller of the two. total_amount already nets out
    # any previously-applied credit lines, so it *is* the remaining balance.
    applied = min(amount, invoice.total_amount) if invoice else amount
    if invoice and applied <= 0:
        return Response({'detail': 'Invoice has no remaining balance to apply credit to.'},
                         status=status.HTTP_400_BAD_REQUEST)

    try:
        with transaction.atomic():
            CreditLedger.spend_credits(tenant, applied, description or 'Credit redemption')
            if invoice:
                from billing.models import InvoiceLine
                InvoiceLine.objects.create(
                    tenant=tenant,
                    invoice=invoice,
                    description=description or 'Referral credit applied',
                    quantity=1,
                    unit_price=-applied,
                )
                invoice.recompute_total()
    except ValueError as exc:
        return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    # Reload balance from DB (spend_credits uses F() update)
    tenant.refresh_from_db(fields=['referral_credits'])

    from activity.utils import log_activity
    log_activity(
        tenant=tenant,
        actor=request.user,
        verb='credits.redeemed',
        description=description or f'Redeemed {applied} credits',
        target_type='invoice' if invoice_id else 'tenant',
        target_id=invoice_id or tenant.id,
        metadata={'requested': str(amount), 'applied': str(applied)},
    )

    return Response({
        'balance': str(tenant.referral_credits),
        'requested': str(amount),
        'applied': str(applied),
        'invoice_total': str(invoice.total_amount) if invoice else None,
    })


# ── Superadmin ────────────────────────────────────────────────────────────────
# NOTE: SuperadminTenantListView, SuperadminUserListView, and
# SuperadminTenantDetailView were removed here — their screens (tenant list,
# tenant detail edit, user list with search/tenant/is_active/role filters)
# are now native ModelAdmin pages at /django-admin/ (tenants.TenantAdmin,
# accounts.UserAdmin — see accounts/admin.py list_filter/search_fields for
# the same filtering surface). The trial-clock-start and activation/
# deactivation email side effects that used to live in
# SuperadminTenantDetailView.perform_update() now live in
# tenants/admin.py::apply_activation_side_effects(), called from both the
# bulk activate/deactivate actions and TenantAdmin.save_model().
# superadmin_trial_summary was also removed — dashboard.py computes the same
# KPIs directly via the ORM for the /django-admin/ index page.


# superadmin_grant_feature and superadmin_trial_summary were removed here.
# Feature grants are now edited directly via TenantFeatureInline on the
# Tenant change form in /django-admin/ (tenants/admin.py). Trial summary is
# now the TrialTenantAdmin list page plus the dashboard.py KPI cards, both
# reading the same Tenant queryset directly via the ORM.