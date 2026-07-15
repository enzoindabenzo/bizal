import logging

logger = logging.getLogger(__name__)
import secrets

from rest_framework import serializers, generics, status as http_status
from rest_framework.response import Response

from tenants.permissions import IsTenantOwner, IsTenantStaff, HasTenantFeature
from .models import StaffMember, StaffSchedule
from .serializers import StaffMemberSerializer, StaffScheduleSerializer

# Staff management is a Pro+ feature (staff_accounts=False on Starter plan).
# Both the list/invite view and the detail/remove view gate on this feature
# so a Starter-plan owner can't manage staff at all.
_staff_feature = HasTenantFeature('staff_accounts')


class StaffDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = StaffMemberSerializer
    permission_classes = [IsTenantOwner, _staff_feature]

    def get_queryset(self):
        return StaffMember.objects.filter(tenant=self.request.tenant)

    def perform_destroy(self, instance):
        """
        FIX #11: Soft-delete (is_active=False) instead of hard DELETE.
        Hard-deleting a StaffMember leaves orphaned history — shifts,
        orders, and bookings that reference this person lose context.
        Soft-delete preserves the audit trail while removing the member
        from all active staff listings.
        """
        from activity.utils import log_activity
        log_activity(
            tenant=self.request.tenant,
            actor=self.request.user,
            verb='staff.removed',
            description=f'Deactivated {instance.user.display_name} from staff',
            target_type='staff_member',
            target_id=instance.id,
        )
        instance.is_active = False
        instance.save(update_fields=['is_active', 'updated_at'])

        # Also deactivate the linked User account so the person can no
        # longer log in to this tenant's portal. Their User row is NOT
        # deleted — that would break FK references on historical records.
        # CRIT-2 FIX: Guard was `user.role in ('staff', 'manager')` which
        # skips users whose User.role is still 'customer' (a customer invited
        # to staff retains role='customer' on the User row if get_or_create
        # found the existing record). Remove the role guard entirely — any
        # user removed from staff should have their login deactivated.
        user = instance.user
        if user:
            user.is_active = False
            user.save(update_fields=['is_active', 'updated_at'])

        # FIX (Security): Flush all outstanding refresh tokens for this user
        # so their 60-minute access window doesn't linger after removal.
        # The access token itself cannot be revoked (stateless JWT), but
        # blacklisting refresh tokens stops any new access tokens being issued.
        try:
            from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
            from rest_framework_simplejwt.tokens import RefreshToken as _RefreshToken
            if user:
                for outstanding in OutstandingToken.objects.filter(user=user):
                    try:
                        token = _RefreshToken(outstanding.token)
                        token.blacklist()
                    except Exception:
                        # MEDIUM-2 FIX: individual token may already be expired/blacklisted — log but continue
                        logger.exception('StaffDetailView: failed to blacklist token for user %s', user.pk)
        except Exception:
            # MEDIUM-2 FIX: log revocation failures so operators can detect when staff tokens remain valid post-removal
            logger.exception('StaffDetailView: token revocation failed for user %s — outstanding refresh tokens may still be valid', user.pk)


class StaffInviteSerializer(serializers.Serializer):
    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=['staff', 'manager', 'receptionist', 'accountant'])


def _perform_staff_invite(request):
    """
    Shared invite logic used by both StaffInviteView (POST /api/staff/invite/,
    if that route exists) and StaffListCreateView (POST /api/staff/).
    Extracted to a plain function so neither view needs to call into the
    other with a duck-typed `self`.
    """
    from accounts.models import User

    ser = StaffInviteSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    # M-1 FIX: normalize email to lowercase so that inviting "Jane@company.com"
    # finds an existing "jane@company.com" user instead of silently creating a
    # second, separate account with a different case.
    email = ser.validated_data['email'].strip().lower()
    role = ser.validated_data['role']
    tenant = request.tenant

    # Check plan limit inside a transaction with select_for_update so that
    # two simultaneous invite requests both at max-1 can't both pass and
    # exceed the plan cap. The lock must be held across both the count check
    # AND the update_or_create write; releasing it in between would reintroduce
    # the TOCTOU race.
    from django.db import transaction
    max_staff = tenant.get_limit('max_staff')
    user_role = role if role == 'manager' else 'staff'
    with transaction.atomic():
        # M-2 FIX: lock the Tenant row itself rather than the existing
        # StaffMember rows.  SELECT FOR UPDATE on a COUNT() only locks rows
        # that already exist — it cannot block a concurrent INSERT of a new
        # StaffMember row that doesn't exist yet (the classic Postgres
        # phantom-insert gap).  Locking the Tenant row serializes all
        # concurrent invite attempts for this tenant through a single,
        # always-existing row, which does block until the first transaction
        # commits, closing the race entirely.
        from tenants.models import Tenant as TenantModel
        TenantModel.objects.select_for_update().get(pk=tenant.pk)

        # FIX: an "invite" for an email that already has an active
        # StaffMember row on this tenant (i.e. this call is really a
        # role-change re-invite, per the HIGH-2 FIX below) must not be
        # blocked by the plan limit — it doesn't add a new person to the
        # roster, it just updates an existing one. Without this check, a
        # tenant sitting exactly at max_staff could never change an
        # existing staff member's role without first removing someone
        # else, even though headcount would stay the same.
        existing_user = User.objects.filter(email=email).first()
        is_existing_active_member = bool(
            existing_user and StaffMember.objects.filter(
                tenant=tenant, user=existing_user, is_active=True,
            ).exists()
        )

        current_count = (
            StaffMember.objects.filter(tenant=tenant, is_active=True).count()
        )
        if max_staff and current_count >= max_staff and not is_existing_active_member:
            return Response(
                {'detail': f'Staff limit reached for your plan ({max_staff}).'},
                status=http_status.HTTP_403_FORBIDDEN,
            )

        # Get or create User — still inside the atomic block so the count
        # lock covers the StaffMember write below.
        # FIX: email is intentionally not globally unique (a person can have
        # a separate account on each tenant they interact with, enforced via
        # UniqueConstraint(['email', 'tenant'])). get_or_create() runs an
        # internal .get(email=email) that raises MultipleObjectsReturned if
        # that email already has accounts on 2+ other tenants, 500ing the
        # invite endpoint instead of returning the intended 400. Look the
        # candidate up explicitly first (preferring this tenant, then a
        # platform-level account, then any match — same tie-break already
        # proven correct in accounts/auth_backends.py) and only create when
        # nothing exists at all.
        existing_candidate = (
            User.objects.filter(email=email, tenant=tenant).order_by('id').first()
            or User.objects.filter(email=email, tenant__isnull=True).order_by('id').first()
            or User.objects.filter(email=email).order_by('id').first()
        )
        if existing_candidate is not None:
            user, created = existing_candidate, False
        else:
            user, created = User.objects.get_or_create(
                email=email,
                defaults={
                    'tenant': tenant,
                    'role': user_role,
                    # Do NOT pass a raw password string here — Django's ORM stores
                    # the value directly in the password column, bypassing the
                    # hasher. Use set_unusable_password() semantics by omitting the
                    # field entirely; set_password() below is the sole place the
                    # credential is ever written.
                }
            )
        if not created:
            if user.tenant is not None and user.tenant != tenant:
                return Response(
                    {'detail': 'This email is already registered to another tenant.'},
                    status=http_status.HTTP_400_BAD_REQUEST,
                )
            if user.tenant is None and user.is_staff:
                # Platform-level superadmin account — cannot be added as tenant staff.
                return Response(
                    {'detail': 'This email is associated with a platform admin account and cannot be added as staff.'},
                    status=http_status.HTTP_400_BAD_REQUEST,
                )
            # user.tenant is None and not is_staff: platform customer — assign them to this
            # tenant so the login view (user.tenant != request.tenant check) and
            # get_effective_role() (user.tenant != tenant check) both pass correctly.
            # Without this assignment the staff member is created in the DB and receives
            # a credentials email, but every subsequent login attempt returns 403 because
            # None != <Tenant>, making the invite silently useless.
            if user.tenant is None:
                user.tenant = tenant
                user.save(update_fields=['tenant', 'updated_at'])

        # HIGH-2 FIX: `defaults` in get_or_create only applies on creation.
        # An existing user re-invited with a different role (e.g. customer->manager,
        # or staff re-invited as manager) retains their old User.role indefinitely,
        # causing IsTenantOwner checks to fail for re-invited managers.
        # Always sync User.role unless they are an owner (don't downgrade owners).
        if not created and user.role not in ('owner',):
            user.role = user_role
            user.save(update_fields=['role', 'updated_at'])

        # Defined here (not just inside `if created`) so it's never unbound
        # if a future refactor separates this block from the `if created`
        # block below that references it.
        temp_password = None
        if created:
            # Generate and hash the temporary password while still inside the
            # atomic block so a failure in the subsequent send_mail() call
            # cannot leave the account without a usable password.
            temp_password = secrets.token_urlsafe(10)
            user.set_password(temp_password)
            # LOW-4 FIX: include 'updated_at' in update_fields to match the
            # codebase-wide pattern of always stamping updated_at on any save()
            # that mutates user state. Omitting it left updated_at stale when
            # a new staff member's password was set at invite time.
            user.save(update_fields=['password', 'updated_at'])

        # Create or reactivate StaffMember — inside the same atomic block.
        member, _ = StaffMember.objects.update_or_create(
            tenant=tenant, user=user,
            defaults={'role': role, 'is_active': True},
        )

    # Notify with the temporary password generated inside the atomic block
    if created:
        try:
            from django.core.mail import send_mail
            from django.conf import settings
            send_mail(
                subject=f'You have been added to {tenant.name} on BizAL',
                message=(
                    f'Hello,\n\nYou have been added as {role} at {tenant.name}.\n\n'
                    f'Email: {email}\nTemporary password: {temp_password}\n\n'
                    f'Please log in and change your password.'
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[email],
                fail_silently=True,
            )
        except Exception:
            pass

    from activity.utils import log_activity
    log_activity(
        tenant=tenant,
        actor=request.user,
        verb='staff.invited',
        description=f'Added {email} as {member.get_role_display()}',
        target_type='staff_member',
        target_id=member.id,
    )

    return Response(StaffMemberSerializer(member).data, status=http_status.HTTP_201_CREATED)


class StaffListCreateView(generics.GenericAPIView):
    """
    GET  /api/staff/ — list active staff (IsTenantStaff)
    POST /api/staff/ — invite new staff (IsTenantOwner)
    """
    def get_serializer_class(self):
        if self.request.method == 'POST':
            return StaffInviteSerializer
        return StaffMemberSerializer

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsTenantOwner(), _staff_feature()]
        return [IsTenantStaff(), _staff_feature()]

    def get_queryset(self):
        return StaffMember.objects.filter(
            tenant=self.request.tenant, is_active=True
        ).select_related('user').prefetch_related('schedules')

    def get(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = StaffMemberSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = StaffMemberSerializer(qs, many=True)
        return Response(serializer.data)

    def post(self, request, *args, **kwargs):
        return _perform_staff_invite(request)


# ── StaffSchedule endpoints ────────────────────────────────────────────────────

class StaffScheduleListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/staff/<uuid:staff_pk>/schedules/ — list schedules for a staff member.
    POST — create or replace a schedule entry for a given day.
    """
    serializer_class = StaffScheduleSerializer
    permission_classes = [IsTenantOwner, _staff_feature]

    def _get_member(self):
        try:
            return StaffMember.objects.get(
                pk=self.kwargs['staff_pk'], tenant=self.request.tenant, is_active=True,
            )
        except StaffMember.DoesNotExist:
            from rest_framework.exceptions import NotFound
            raise NotFound('Staff member not found.')

    def get_queryset(self):
        return self._get_member().schedules.all()

    def perform_create(self, serializer):
        member = self._get_member()
        from .models import StaffSchedule
        # Upsert: if this day already has a schedule, replace it.
        StaffSchedule.objects.filter(staff=member, day=serializer.validated_data['day']).delete()
        serializer.save(staff=member, tenant=self.request.tenant)


class StaffScheduleDetailView(generics.RetrieveUpdateDestroyAPIView):
    """PUT/PATCH/DELETE a single schedule entry."""
    serializer_class   = StaffScheduleSerializer
    permission_classes = [IsTenantOwner, _staff_feature]

    def get_queryset(self):
        try:
            member = StaffMember.objects.get(
                pk=self.kwargs['staff_pk'], tenant=self.request.tenant,
            )
        except StaffMember.DoesNotExist:
            return StaffSchedule.objects.none()  # type: ignore[attr-defined]
        from .models import StaffSchedule
        return StaffSchedule.objects.filter(staff=member)
