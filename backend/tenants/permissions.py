from rest_framework.permissions import BasePermission


class TenantDomainOnly(BasePermission):
    def has_permission(self, request, view):
        return request.tenant is not None


class MainDomainOnly(BasePermission):
    def has_permission(self, request, view):
        return request.tenant is None


class IsTenantOwner(BasePermission):
    def has_permission(self, request, view):
        if not request.tenant or not request.user.is_authenticated:
            return False
        return (
            request.user.is_superuser
            or (hasattr(request.user, 'tenant') and request.user.tenant == request.tenant and request.user.role in ('owner', 'manager'))
        )


class IsTenantStaff(BasePermission):
    def has_permission(self, request, view):
        if not request.tenant or not request.user.is_authenticated:
            return False
        return (
            request.user.is_superuser
            or (hasattr(request.user, 'tenant') and request.user.tenant == request.tenant)
        )


class HasTenantFeature:
    def __init__(self, feature_key):
        self.feature_key = feature_key

    def __call__(self):
        feature_key = self.feature_key

        class FeaturePermission(BasePermission):
            def has_permission(self, request, view):
                if not request.tenant:
                    return False
                return request.tenant.has_feature(feature_key)

        return FeaturePermission()
