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

    # HIGH-1 / MEDIUM-1 FIX: Use the StaffMember table as the sole
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
