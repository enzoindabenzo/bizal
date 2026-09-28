from rest_framework.permissions import BasePermission


class TenantDomainOnly(BasePermission):
    # FIX: Added explicit message so the 403 response body names the actual
    # cause instead of DRF's generic "You do not have permission to perform
    # this action." This prevents the frontend from misinterpreting the 403
    # as an auth failure and retrying in a tight loop.
    message = 'This endpoint requires a business subdomain. Please access it via <slug>.bizal.al.'

    def has_permission(self, request, view):
        return request.tenant is not None


class MainDomainOnly(BasePermission):
    message = 'Business signup must be done from the main BizAL site, not a business portal.'

    def has_permission(self, request, view):
        return request.tenant is None


def get_effective_role(user, tenant):
    """
    Return the effective staff role a user has within a tenant, or None if
    the user has no staff-level access to this tenant at all.

    - 'owner' / 'manager' on the User itself are the top management tier and
      are returned as-is.
    - Otherwise, look for an active staff.StaffMember record for this user
      and tenant (roles: 'manager', 'receptionist', 'accountant', 'staff').
    - A plain 'customer' with no StaffMember record returns None — customers
      are not staff, even though they belong to the tenant.
    """
    if not user or not user.is_authenticated:
        return None
    if not hasattr(user, 'tenant') or user.tenant != tenant:
        return None

    if user.role in ('owner', 'manager'):
        return user.role

    # Use the StaffMember table as the sole
    # authoritative source for staff status instead of the previous two-step
    # approach (getattr(user, 'staff_profile', None) → user.role == 'staff'
    # fallback).
    #
    # The old fallback was unsafe: perform_destroy() sets User.is_active=False
    # but leaves User.role='staff'. A superadmin re-activating the User account
    # (e.g. to restore a customer account) without reinstating the StaffMember
    # row would cause get_effective_role() to return 'staff' for that user —
    # granting access to every IsTenantStaff-gated endpoint with no active
    # StaffMember record.
    #
    # The getattr() accessor also triggered a live SELECT on every call when
    # staff_profile was not prefetched (reverse OneToOneField descriptor), making
    # it a silent N+1 on every staff-gated request.
    #
    # Fix: query StaffMember directly. The explicit ORM call is transparent,
    # cache-friendly, and avoids both correctness and performance problems.
    # Callers that already select_related('staff_profile') continue to benefit
    # from that prefetch for other purposes; the permission check is now
    # independent of prefetch state.
    try:
        from staff.models import StaffMember
        sm = StaffMember.objects.get(user=user, tenant=tenant, is_active=True)
        return sm.role
    except Exception:
        return None


class IsTenantOwner(BasePermission):
    def has_permission(self, request, view):
        if not request.tenant or not request.user.is_authenticated:
            return False
        return (
            request.user.is_superuser
            or (hasattr(request.user, 'tenant') and request.user.tenant == request.tenant and request.user.role in ('owner', 'manager'))
        )


class IsTenantStaff(BasePermission):
    """
    Any staff member of the current tenant (owner, manager, receptionist,
    accountant, or generic staff) — but NOT a plain customer. Customers
    belong to the tenant too (request.user.tenant == request.tenant) but
    have no staff role, so they must not pass this check.
    """
    def has_permission(self, request, view):
        if not request.tenant or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        return get_effective_role(request.user, request.tenant) is not None


def HasTenantRole(*roles):
    """
    Permission factory restricting access to specific staff roles within
    the tenant. Owners and managers always pass (management tier), plus
    whichever additional roles are listed.

    Usage:
        permission_classes = [HasTenantRole('accountant')]
        permission_classes = [HasTenantRole('receptionist', 'accountant')]

    Returns a proper BasePermission subclass so DRF can instantiate it
    cleanly via HasTenantRole('accountant')() — the standard DRF pattern.
    """
    _roles = set(roles) | {'owner', 'manager'}

    class _HasTenantRole(BasePermission):
        def has_permission(self, request, view):
            if not request.tenant or not request.user.is_authenticated:
                return False
            if request.user.is_superuser:
                return True
            role = get_effective_role(request.user, request.tenant)
            return role is not None and role in _roles

    _HasTenantRole.__name__ = f"HasTenantRole({', '.join(sorted(roles))})"
    return _HasTenantRole


def HasTenantFeature(feature_key):
    """
    Permission factory. Returns a fresh BasePermission subclass each time,
    so DRF's standard instantiation pattern works correctly and permission
    classes with different feature_keys don't share state.

    Usage:
        permission_classes = [IsTenantOwner, HasTenantFeature('blog')]
    """
    class _HasTenantFeature(BasePermission):
        def has_permission(self, request, view):
            if not request.tenant:
                return False
            return request.tenant.has_feature(feature_key)

    _HasTenantFeature.__name__ = f"HasTenantFeature({feature_key!r})"
    return _HasTenantFeature


def HasPlanAtLeast(*plans):
    """
    Permission factory restricting access to tenants on one of the given
    plan tiers (e.g. HasPlanAtLeast('pro', 'enterprise')). Superusers always
    pass. Use this for features that are gated by plan tier directly rather
    than by a TenantFeature flag — e.g. subscriptions/views.py previously had
    no plan check at all on its owner-facing endpoints even though the
    tenant admin nav only surfaces "Abonimet" for pro/enterprise plans,
    meaning a Starter-plan tenant's accountant could use the API directly
    to bypass that restriction entirely.
    """
    _plans = set(plans)

    class _HasPlanAtLeast(BasePermission):
        def has_permission(self, request, view):
            if not request.tenant:
                return False
            if request.user.is_authenticated and request.user.is_superuser:
                return True
            return request.tenant.plan in _plans

    _HasPlanAtLeast.__name__ = f"HasPlanAtLeast({', '.join(sorted(plans))})"
    return _HasPlanAtLeast


class IsOwnTenantStaff(BasePermission):
    """
    Like IsTenantStaff, but checks the user's OWN tenant (user.tenant)
    rather than the subdomain the request came in on (request.tenant).
    For endpoints like /api/tenants/me/ that operate on "my tenant"
    regardless of which domain the request hit.
    """
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        tenant = getattr(request.user, 'tenant', None)
        if tenant is None:
            return False
        return get_effective_role(request.user, tenant) is not None


class MatchesRequestTenant(BasePermission):
    """
    For customer-facing "my account" endpoints (MeView, MeBookingsView,
    MeOrdersView, MeAppointmentsView, MeReviewsView, MeNotificationPrefsView,
    etc). IsAuthenticated alone only proves the JWT is valid — it says
    nothing about which tenant the token's owner actually registered on.

    A registered user's User.tenant is fixed at registration
    (accounts/views.py RegisterView.perform_create). If the request is
    tenant-scoped (hit via <slug>.bizal.al, or ?tenant=<slug> on a
    deployment using ALLOW_TENANT_QUERY_PARAM) but the authenticated
    user's own tenant doesn't match request.tenant, the token should be
    treated as not-logged-in *here* — not silently accepted as if the
    person had an account on this tenant.

    This closes a real leak: a JWT/refresh token is portable JS state.
    On subdomain-based tenancy each tenant is a separate browser origin,
    so localStorage/memory naturally keeps sessions apart — but nothing
    on the API itself enforced that separation. Any request that carries
    a token — including a leftover refresh token shared across tenants on
    a single-origin deployment (e.g. the Railway ?tenant= fallback, where
    every tenant shares one origin and therefore one localStorage) — was
    silently authenticated as whichever account the token belonged to,
    regardless of which tenant it was issued for.

    Superusers are exempt (needed for superadmin tooling that legitimately
    inspects any tenant). A request with no tenant at all (main-domain
    account page) passes through unchanged.
    """
    message = 'This account is not registered on this business.'

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.tenant is None:
            return True
        return getattr(request.user, 'tenant_id', None) == request.tenant.id


class IsOwnTenantOwnerOrManager(BasePermission):
    """Like IsOwnTenantStaff, but restricted to owner/manager."""
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        tenant = getattr(request.user, 'tenant', None)
        if tenant is None:
            return False
        return get_effective_role(request.user, tenant) in ('owner', 'manager')