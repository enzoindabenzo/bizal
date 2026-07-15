import logging

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.tokens import RefreshToken
from django.conf import settings as django_settings
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.core.mail import send_mail
from rest_framework.pagination import PageNumberPagination
from bookings.models import Booking
from bookings.serializers import BookingSerializer
from reviews.models import Review

import functools
from .models import User
from .serializers import RegisterSerializer, UserProfileSerializer, CustomTokenObtainPairSerializer

# MED-4 FIX: Cache the dummy password hash so the bcrypt work only runs once.
# NOTE: @lru_cache is lazy — the hash is computed on the first not-found
# password-reset request, not at container startup. The DB round-trip
# (timing_sink query in PasswordResetRequestView) is the dominant timing
# equaliser between the found/not-found branches; the cached hash eliminates
# repeated bcrypt cost from the second not-found request onward.
@functools.lru_cache(maxsize=1)
def _get_dummy_password_hash():
    from django.contrib.auth.hashers import make_password as _mp
    return _mp('dummy-sink-password-fixed-at-startup')

from bizal.ratelimit_utils import ratelimit_decorator as _ratelimit_decorator

logger = logging.getLogger(__name__)


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]

    @method_decorator(csrf_exempt)
    @method_decorator(_ratelimit_decorator('5/m'))
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        # BUG FIX: RegisterSerializer only ever returned {email, full_name,
        # phone} — no access/refresh tokens — so the frontend's
        # `if (d.access) Auth.setTokens(...)` silently never fired and a
        # freshly registered user was left logged out despite the account
        # existing. Issue JWTs here the same way tenant_signup()/create_tenant()
        # already do, so registration behaves like an immediate login.
        response = super().create(request, *args, **kwargs)
        if response.status_code == status.HTTP_201_CREATED:
            user = self._registered_user
            refresh = RefreshToken.for_user(user)
            response.data['access'] = str(refresh.access_token)
            response.data['refresh'] = str(refresh)
            response.data['user_id'] = str(user.id)
        return response

    def perform_create(self, serializer):
        tenant = getattr(self.request, 'tenant', None)
        user = serializer.save(tenant=tenant, role='customer')
        self._registered_user = user
        # Send email verification link asynchronously (non-blocking)
        try:
            from django.utils.encoding import force_bytes
            from django.utils.http import urlsafe_base64_encode
            # H-1 FIX: use the email-verification-specific generator, not the
            # shared default_token_generator also used for password resets —
            # see accounts/tokens.py for why sharing one generator lets a
            # token minted for one flow be replayed against the other.
            from .tokens import email_verification_token_generator
            uid   = urlsafe_base64_encode(force_bytes(user.pk))
            token = email_verification_token_generator.make_token(user)
            base  = django_settings.FRONTEND_BASE_URL
            link  = f"{base}/verify-email/{uid}/{token}/"
            send_mail(
                subject='Verifikoni email-in tuaj — BizAL',
                message=(
                    f"Përshëndetje {user.display_name},\n\n"
                    f"Kliko linkun për të verifikuar email-in:\n\n{link}\n\n"
                    "Ky link skadon pas 1 ore."
                ),
                from_email=django_settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=True,
            )
        except Exception:
            pass  # Non-fatal — user can request re-send from account settings


class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer

    @method_decorator(csrf_exempt)
    @method_decorator(_ratelimit_decorator('5/m'))
    def post(self, request, *args, **kwargs):
        # H-1 FIX: Validate inline on a single serializer instance so that
        # .user is available on the same object after is_valid().  Raising
        # raise_exception=True lets SimpleJWT's AuthenticationFailed propagate
        # naturally through DRF's exception handler — no try/except needed and
        # no second validation cycle on failed credentials.
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.user  # set on this instance by validate()
        response = Response(serializer.validated_data, status=status.HTTP_200_OK)

        # Main domain: block users that belong to a specific tenant.
        # Platform-level users (tenant=None) and superadmin/staff always allowed.
        #
        # EXCEPTION: a tenant whose onboarding wizard isn't finished yet
        # (onboarding_complete=False) is exempted from this block. The
        # onboarding wizard itself only exists on the main domain — a brand
        # new owner is dropped there straight from /tenants/signup/ using
        # tokens minted at signup time, with no /auth/login/ call involved.
        # But if that in-memory access token is lost before onboarding is
        # finished (closed tab, expired refresh token, different device/
        # browser) their only way back in is /auth/login/ on the main
        # domain — blocking it here would strand them with a tenant they
        # can never finish setting up. Once onboarding_complete flips to
        # True, this exception no longer applies and they're routed to
        # their business portal like every other tenant user.
        user_onboarding_incomplete = user.tenant is not None and not user.tenant.onboarding_complete
        if request.tenant is None and not user.is_staff and user.tenant is not None and not user_onboarding_incomplete:
            return Response(
                {
                    'detail': 'Please log in from your business portal.',
                    'redirect_slug': user.tenant.slug,
                },
                status=status.HTTP_403_FORBIDDEN
            )
        # Reject cross-tenant login AND block superadmins from tenant
        # subdomains — they authenticate via /admin/, not through the
        # tenant JWT flow.  The previous check (`not user.is_superuser`)
        # let superadmins log in to any tenant subdomain, giving them a
        # valid tenant JWT they should never hold.
        if request.tenant:
            if user.is_superuser:
                return Response(
                    {'detail': 'Superadmins must use the admin panel, not a tenant portal.'},
                    status=status.HTTP_403_FORBIDDEN
                )
            if user.tenant != request.tenant:
                return Response(
                    {'detail': 'Invalid credentials for this portal.'},
                    status=status.HTTP_403_FORBIDDEN
                )
        return response


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    @method_decorator(csrf_exempt)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def post(self, request):
        try:
            refresh_token = request.data['refresh']
            token = RefreshToken(refresh_token)
            token.blacklist()
            return Response({'detail': 'Logged out.'}, status=status.HTTP_200_OK)
        except Exception:
            return Response({'detail': 'Invalid token.'}, status=status.HTTP_400_BAD_REQUEST)


class MeView(generics.RetrieveUpdateAPIView):
    serializer_class = UserProfileSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        # H-2 FIX (v43): Return user with select_related('staff_profile', 'tenant')
        # so that UserProfileSerializer.get_staff_role() and get_tenant_name() /
        # get_tenant_slug() can access those relations without issuing extra queries.
        # Previously this returned self.request.user directly; JWTAuthentication
        # loads the user without any related objects, so every /api/auth/me/ call
        # for a staff user fired two DB queries (user + staff_profile). Adding
        # select_related here collapses both into a single JOIN.
        return (
            self.request.user.__class__.objects
            .select_related('staff_profile', 'tenant')
            .get(pk=self.request.user.pk)
        )


class ChangePasswordView(APIView):
    """Authenticated user changes their own password."""
    permission_classes = [IsAuthenticated]

    @method_decorator(csrf_exempt)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    @method_decorator(_ratelimit_decorator('5/m'))
    def post(self, request):
        user = request.user
        old_password = request.data.get('old_password', '')
        new_password = request.data.get('new_password', '')

        if not old_password or not new_password:
            return Response(
                {'detail': 'old_password and new_password are required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not user.check_password(old_password):
            return Response(
                {'detail': 'Old password is incorrect.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Run the full AUTH_PASSWORD_VALIDATORS suite (common-password list,
        # similarity check, min-length, numeric-only check) — previously only
        # the length was checked, letting weak passwords like "password1" through.
        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError as DjangoValidationError
        try:
            validate_password(new_password, user=user)
        except DjangoValidationError as exc:
            return Response({'detail': list(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)
        user.set_password(new_password)
        user.save(update_fields=['password', 'updated_at'])

        # MED-1 FIX: Blacklist all outstanding refresh tokens so that active
        # sessions on other devices (including an attacker who knew the old
        # password) cannot mint new access tokens after the password change.
        # Mirrors PasswordResetConfirmView, MeDeleteView, and StaffDetailView
        # which all do this correctly. Without this, a stolen refresh token
        # remains valid for up to REFRESH_TOKEN_LIFETIME (7 days) after the
        # victim changes their password to lock the attacker out.
        try:
            from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
            from rest_framework_simplejwt.tokens import RefreshToken as _RT
            for t in OutstandingToken.objects.filter(user=user):
                try:
                    _RT(t.token).blacklist()
                except Exception:
                    # MEDIUM-2 FIX: individual token may already be expired/blacklisted — log but continue
                    logger.exception('ChangePasswordView: failed to blacklist token %s for user %s', t.pk, user.pk)
        except Exception:
            # MEDIUM-2 FIX: blacklisting must not silently fail — log so operators can detect revocation gaps
            logger.exception('ChangePasswordView: token revocation failed for user %s — outstanding refresh tokens may still be valid', user.pk)

        return Response({'detail': 'Password changed successfully.'})


class PasswordResetRequestView(APIView):
    """Send a password-reset link to the user's email."""
    permission_classes = [AllowAny]

    @method_decorator(csrf_exempt)
    @method_decorator(_ratelimit_decorator('3/m'))
    def post(self, request):
        email = request.data.get('email', '').strip().lower()
        if not email:
            return Response({'detail': 'Email is required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            lookup = {'email': email}
            request_tenant = getattr(request, 'tenant', None)
            if request_tenant is not None:
                lookup['tenant'] = request_tenant
            # FIX: email is intentionally not globally unique (a person can
            # have a separate account on each tenant they interact with,
            # enforced via UniqueConstraint(['email', 'tenant'])). When the
            # request comes from the main domain (request_tenant is None),
            # lookup has no tenant filter, so a shared email with accounts on
            # 2+ tenants makes User.objects.get() raise MultipleObjectsReturned
            # instead of returning the intended generic response. Use a
            # deterministic filter().order_by('id').first() instead, matching
            # the tie-break already used by TenantAwareModelBackend.
            user = User.objects.filter(**lookup).order_by('id').first()
            if user is None:
                raise User.DoesNotExist
        except User.DoesNotExist:
            # MEDIUM-2 FIX: Replace the fixed sentinel address
            # ('__timing_sink__@deleted.bizal.al') with a query on the same
            # normalised email the request just sent.  The sentinel was
            # deterministic — after a few requests the DB cache warmed its
            # always-missing index slot, making the not-found path measurably
            # faster than the found-user path (live index tuple → heap fetch).
            # Querying the actual email takes the same index path (live or not)
            # regardless of whether the user exists, eliminating the differential.
            import hmac as _hmac
            User.objects.filter(email=email).exists()
            _hmac.compare_digest('', '')  # keep branch predictor warm
            # LOW-6 FIX: Use a realistic bcrypt/argon2-length password hash for
            # the dummy user so make_token()'s HMAC input length matches the
            # found-user path. The previous password='!' was 1 character vs ~60
            # for a real hash, creating a sub-nanosecond but measurable timing
            # difference on high-resolution side-channel analysis. The found-user
            # path calls make_token(user) over a full-length hash; the not-found
            # path runs the same operation here to equalise both branches.
            _dummy = User(email='__sink__@deleted.bizal.al', password=_get_dummy_password_hash())
            default_token_generator.make_token(_dummy)
            return Response({'detail': 'If that email exists, a reset link has been sent.'})

        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        # LOW-4 FIX: Always route reset links to the main domain. The previous
        # code sent links to https://{slug}.bizal.al/reset-password/... when the
        # request came from a tenant subdomain, but /reset-password/ may not be
        # a handled route in the tenant SPA, resulting in a blank page. The main
        # domain SPA always handles /reset-password/<uid>/<token>/ correctly.
        base_url = django_settings.FRONTEND_BASE_URL
        if not base_url:
            logger.error(
                'PasswordResetRequestView: FRONTEND_BASE_URL is not set; '
                'reset link will be broken for user %s', user.pk
            )
            base_url = 'https://bizal.al'  # safe fallback — never an empty string
        reset_url = f"{base_url}/reset-password/{uid}/{token}/"

        try:
            send_mail(
                subject='Password Reset — BizAL',
                message=f"Click the link below to reset your password:\n\n{reset_url}\n\nThis link expires in 1 hour.",
                from_email=django_settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=False,
            )
        except Exception as exc:
            logger.error(
                'PasswordResetRequestView: email delivery failed for user %s: %s',
                user.pk, exc,
            )
        return Response({'detail': 'If that email exists, a reset link has been sent.'})


class PasswordResetConfirmView(APIView):
    """Confirm the reset token and set a new password."""
    permission_classes = [AllowAny]

    @method_decorator(csrf_exempt)
    @method_decorator(_ratelimit_decorator('5/m'))
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def post(self, request):
        uid = request.data.get('uid', '')
        token = request.data.get('token', '')
        new_password = request.data.get('new_password', '')

        if not uid or not token or not new_password:
            return Response(
                {'detail': 'uid, token, and new_password are required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            user_pk = force_str(urlsafe_base64_decode(uid))
            user = User.objects.get(pk=user_pk)
        except (User.DoesNotExist, ValueError, TypeError):
            return Response({'detail': 'Invalid reset link.'}, status=status.HTTP_400_BAD_REQUEST)

        if not default_token_generator.check_token(user, token):
            return Response({'detail': 'Reset link is invalid or has expired.'}, status=status.HTTP_400_BAD_REQUEST)

        # Run the full AUTH_PASSWORD_VALIDATORS suite (common-password list,
        # similarity-to-user-attributes check, min-length, numeric-only check)
        # — same validation ChangePasswordView runs. Previously this only
        # checked length, so a reset could set the account to a common
        # password like "password1" that the change-password flow would
        # reject for the same user.
        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError as DjangoValidationError
        try:
            validate_password(new_password, user=user)
        except DjangoValidationError as exc:
            return Response({'detail': list(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(new_password)
        user.save(update_fields=['password', 'updated_at'])

        # HIGH-1 FIX: Blacklist all outstanding refresh tokens so that an
        # attacker who obtained a valid refresh token (e.g. from a stolen
        # session) cannot retain API access after the owner resets their
        # password. MeDeleteView and StaffDetailView.perform_destroy() both
        # do this too; password reset must match.
        try:
            from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
            from rest_framework_simplejwt.tokens import RefreshToken as _RT
            for t in OutstandingToken.objects.filter(user=user):
                try:
                    _RT(t.token).blacklist()
                except Exception:
                    # MEDIUM-2 FIX: individual token may already be expired/blacklisted — log but continue
                    logger.exception('PasswordResetConfirmView: failed to blacklist token %s for user %s', t.pk, user.pk)
        except Exception:
            # MEDIUM-2 FIX: blacklisting must not silently fail — log so operators can detect revocation gaps
            logger.exception('PasswordResetConfirmView: token revocation failed for user %s — outstanding refresh tokens may still be valid', user.pk)

        return Response({'detail': 'Password has been reset successfully.'})


class _StandardPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class MeBookingsView(APIView):
    permission_classes = [IsAuthenticated]

    # FIX #10: Use proper pagination instead of [:50] hardcoded slice
    def get(self, request):
        # L-3 FIX (v43): Add select_related('tenant') so BookingSerializer can
        # access booking.tenant.name / tenant.slug without a per-row extra query.
        qs = Booking.objects.filter(user=request.user).select_related('user', 'tenant')
        tenant_slug = request.query_params.get('tenant')
        if tenant_slug:
            qs = qs.filter(tenant__slug=tenant_slug)
        qs = qs.order_by('-created_at')

        paginator = _StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        if page is not None:
            return paginator.get_paginated_response(
                BookingSerializer(page, many=True, context={'request': request}).data
            )
        return Response(BookingSerializer(qs, many=True, context={'request': request}).data)


class MeOrdersView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.db.utils import ProgrammingError as _ProgrammingError
        try:
            from orders.models import Order
            from orders.serializers import OrderSerializer
            qs = Order.objects.filter(user=request.user)
            tenant_slug = request.query_params.get('tenant')
            if tenant_slug:
                qs = qs.filter(tenant__slug=tenant_slug)
            qs = qs.order_by('-created_at')

            paginator = _StandardPagination()
            page = paginator.paginate_queryset(qs, request)
            if page is not None:
                return paginator.get_paginated_response(OrderSerializer(page, many=True).data)
            return Response(OrderSerializer(qs, many=True).data)
        except _ProgrammingError:
            # MEDIUM-4 FIX: re-raise database schema errors (unapplied
            # migrations, missing columns) so Django's exception middleware
            # processes them and triggers mail_admins alerts. Swallowing these
            # silently meant operators would never receive an email notification
            # when this endpoint was broken by a missing migration.
            logger.exception('MeOrdersView: database schema error — check for unapplied migrations')
            raise
        except Exception:
            # Log the real error — silently returning [] with HTTP 200 made
            # broken migrations and import errors completely invisible to
            # clients. Return 500 so the frontend can show a proper error
            # message instead of an empty list with no explanation.
            logger.exception('MeOrdersView: failed to fetch orders for user %s', request.user.pk)
            return Response({'detail': 'Gabim gjatë ngarkimit të porosive.'}, status=500)

class MeReviewsView(APIView):
    permission_classes = [IsAuthenticated]

    # FIX #10: Paginate reviews — previously returned all with no limit
    def get(self, request):
        qs = Review.objects.filter(user=request.user).select_related('tenant')
        tenant_slug = request.query_params.get('tenant')
        if tenant_slug:
            qs = qs.filter(tenant__slug=tenant_slug)
        qs = qs.order_by('-created_at')

        paginator = _StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        items = page if page is not None else qs
        data = [
            {
                'id': str(rv.id),
                'tenant_name': rv.tenant.name if rv.tenant else '',
                'rating': rv.rating,
                'comment': rv.comment,
                'created_at': rv.created_at.date().isoformat(),
                'status': 'approved' if rv.is_approved else 'pending',
            }
            for rv in items
        ]
        if page is not None:
            return paginator.get_paginated_response(data)
        return Response(data)




class MeAppointmentsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.db.utils import ProgrammingError as _ProgrammingError
        try:
            from appointments.models import Appointment
            from appointments.serializers import AppointmentSerializer
            qs = Appointment.objects.filter(user=request.user)
            tenant_slug = request.query_params.get('tenant')
            if tenant_slug:
                qs = qs.filter(tenant__slug=tenant_slug)
            qs = qs.select_related('service', 'provider').order_by('-date', '-start_time')

            paginator = _StandardPagination()
            page = paginator.paginate_queryset(qs, request)
            if page is not None:
                return paginator.get_paginated_response(
                    AppointmentSerializer(page, many=True, context={'request': request}).data
                )
            return Response(AppointmentSerializer(qs, many=True, context={'request': request}).data)
        except _ProgrammingError:
            # MEDIUM-4 FIX: re-raise database schema errors so Django's
            # exception middleware triggers mail_admins alerts.
            logger.exception('MeAppointmentsView: database schema error — check for unapplied migrations')
            raise
        except Exception:
            # Same reasoning as MeOrdersView above — log and return 500 so
            # genuine errors surface to the client rather than silently
            # appearing as an empty appointments list with HTTP 200.
            logger.exception('MeAppointmentsView: failed to fetch appointments for user %s', request.user.pk)
            return Response({'detail': 'Gabim gjatë ngarkimit të takimeve.'}, status=500)


class MeDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request):
        user = request.user

        # Guard: prevent an owner from deleting their account while they are
        # the ONLY owner of an active tenant. Doing so would leave the tenant
        # permanently unmanageable (no one could log in as owner to transfer
        # ownership or cancel the subscription).
        if hasattr(user, 'tenant') and user.tenant is not None and user.role == 'owner':
            tenant = user.tenant
            other_owners = tenant.users.filter(role='owner', is_active=True).exclude(pk=user.pk)
            if not other_owners.exists():
                return Response(
                    {'detail': (
                        'You are the only owner of this account. '
                        'Please transfer ownership to another user before deleting your account.'
                    )},
                    status=400,
                )

        # FIX #3: Deactivate linked StaffMember record so deleted user
        # no longer appears in staff lists.
        try:
            from staff.models import StaffMember
            StaffMember.objects.filter(user=user).update(is_active=False)
        except Exception:
            pass  # Non-fatal — account anonymisation proceeds regardless

        # Anonymise rather than hard-delete so bookings/orders stay intact.
        # LOW-1 FIX: Delete the avatar file from storage before anonymising so
        # the user's personal photo doesn't persist after deletion (GDPR risk
        # and orphaned media accumulation at scale).
        user.is_active = False
        if user.avatar:
            user.avatar.delete(save=False)
            user.avatar = None
        user.email = f'deleted_{user.id}@deleted.bizal.al'
        user.full_name = ''
        user.phone = ''
        # LOW-2 FIX: clear city and business_name — both are user-entered PII
        # that survived the previous anonymisation pass and remained visible in
        # Django admin and the superadmin user list after account deletion.
        user.city = ''
        user.business_name = ''
        # LOW-4 FIX (v36): reset is_email_verified so anonymised accounts don't
        # appear as verified in Django admin (misleading) and don't bootstrap a
        # stale verified state if any future account-recovery logic reads this flag.
        user.is_email_verified = False
        user.notification_prefs = {}
        user.save(update_fields=['is_active', 'avatar', 'email', 'full_name', 'phone', 'city', 'business_name', 'is_email_verified', 'notification_prefs', 'updated_at'])

        # FIX (L-4): Blacklist ALL outstanding refresh tokens for this user,
        # not just the one (if any) submitted in the request body. Only
        # blacklisting the submitted token left active sessions on other
        # devices able to mint new access tokens for up to
        # ACCESS_TOKEN_LIFETIME after the account was "deleted". Mirrors
        # PasswordResetConfirmView, which already does this correctly.
        try:
            from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
            from rest_framework_simplejwt.tokens import RefreshToken as _RT
            for t in OutstandingToken.objects.filter(user=user):
                try:
                    _RT(t.token).blacklist()
                except Exception:
                    # MEDIUM-2 FIX: log individual token failures
                    logger.exception('MeDeleteView: failed to blacklist token %s for user %s', t.pk, user.pk)
        except Exception:
            # MEDIUM-2 FIX: log revocation failures; account is anonymised but tokens may still mint access tokens
            logger.exception('MeDeleteView: token revocation failed for user %s — outstanding refresh tokens may still be valid', user.pk)
        return Response({'detail': 'Account deactivated.'}, status=status.HTTP_200_OK)


class MeNotificationPrefsView(APIView):
    """
    GET   /api/auth/me/notifications/ — current per-channel opt-in flags
    PATCH /api/auth/me/notifications/ — merge in updated flags

    Backs the account settings "Notifications" tab. Stored as a flat JSON
    object on User.notification_prefs. Valid keys are: booking, order,
    reminder, promo, news. Unknown keys are rejected with HTTP 400.
    Values must be booleans. To add a new channel, add it to ALLOWED_KEYS
    in the patch() method below AND update this docstring.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(request.user.notification_prefs or {})

    def patch(self, request):
        if not isinstance(request.data, dict):
            return Response({'detail': 'Expected a JSON object of preference flags.'}, status=400)
        # MEDIUM-3 FIX: prevent storage abuse — an authenticated user could send
        # megabytes of arbitrary JSON that Django would write directly to the user row,
        # bloating the accounts_user table and increasing serialisation cost on every
        # GET /api/auth/me/ call.
        ALLOWED_KEYS = {'booking', 'order', 'reminder', 'promo', 'news'}
        if len(request.data) > len(ALLOWED_KEYS):
            return Response({'detail': 'Too many preference keys.'}, status=400)
        for key, value in request.data.items():
            if key not in ALLOWED_KEYS:
                return Response({'detail': f'Unknown preference key: {key!r}.'}, status=400)
            if not isinstance(value, bool):
                return Response({'detail': 'Preference values must be booleans.'}, status=400)
        prefs = dict(request.user.notification_prefs or {})
        prefs.update(request.data)
        request.user.notification_prefs = prefs
        request.user.save(update_fields=['notification_prefs', 'updated_at'])
        return Response(prefs)


class EmailVerificationSendView(APIView):
    """POST /api/auth/verify-email/ — send/re-send the verification link."""
    permission_classes = [IsAuthenticated]

    # LOW-4 FIX: add per-user rate limit to prevent SMTP quota exhaustion if a
    # JWT token is stolen. Mirrors the pattern used by PasswordResetRequestView.
    @method_decorator(_ratelimit_decorator('3/m'))
    def post(self, request):
        user = request.user
        if user.is_email_verified:
            return Response({'detail': 'Email already verified.'})

        uid   = urlsafe_base64_encode(force_bytes(user.pk))
        # H-1 FIX: dedicated generator — see accounts/tokens.py.
        from .tokens import email_verification_token_generator
        token = email_verification_token_generator.make_token(user)
        base  = django_settings.FRONTEND_BASE_URL
        link  = f"{base}/verify-email/{uid}/{token}/"

        try:
            send_mail(
                subject='Verifikoni email-in tuaj — BizAL',
                message=(
                    f"Përshëndetje {user.display_name},\n\n"
                    f"Kliko linkun më poshtë për të verifikuar email-in tuaj:\n\n{link}\n\n"
                    "Ky link skadon pas 1 ore.\n\nFaleminderit!"
                ),
                from_email=django_settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=False,
            )
        except Exception:
            return Response({'detail': 'Gabim gjatë dërgimit të email-it.'}, status=502)

        return Response({'detail': 'Linku i verifikimit u dërgua.'})


class EmailVerificationConfirmView(APIView):
    """GET /api/auth/verify-email/<uid>/<token>/ — confirm email."""
    permission_classes = []
    authentication_classes = []

    def get(self, request, uid, token):
        try:
            pk   = force_str(urlsafe_base64_decode(uid))
            user = User.objects.get(pk=pk)
        except (User.DoesNotExist, ValueError, TypeError):
            return Response({'detail': 'Link i pavlefshëm.'}, status=400)

        # MED-1 FIX: Reject verification attempts for deactivated/anonymised
        # accounts. Without this guard, a verification link emailed before
        # deletion (valid for 1 hour) could mark the anonymised placeholder
        # address as verified, creating inconsistent data that could be
        # exploited in future account-recovery logic.
        if not user.is_active:
            return Response({'detail': 'Link i pavlefshëm.'}, status=400)

        # H-1 FIX: check against the email-verification-specific generator,
        # not the shared default_token_generator (also used for password
        # resets) — see accounts/tokens.py.
        from .tokens import email_verification_token_generator
        if not email_verification_token_generator.check_token(user, token):
            return Response({'detail': 'Linku ka skaduar ose është i pavlefshëm.'}, status=400)

        user.is_email_verified = True
        user.save(update_fields=['is_email_verified', 'updated_at'])
        return Response({'detail': 'Email u verifikua me sukses!'})