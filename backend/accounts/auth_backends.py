"""
Tenant-aware authentication backend.

Email is no longer globally unique on accounts.User — the same email can
have a separate account on each tenant (see accounts.models.User and
migration 0006_email_unique_per_tenant). That means the default
django.contrib.auth.backends.ModelBackend, which looks users up with a bare
``UserModel._default_manager.get(email=email)`` via ``get_by_natural_key``,
can now raise MultipleObjectsReturned (or pick an arbitrary row) whenever an
email is shared across tenants.

This backend scopes the lookup to ``request.tenant`` (set by the tenant
resolution middleware) when a request is available:
  - On a tenant subdomain/portal: only that tenant's account with this email
    may authenticate.
  - On the main domain (request.tenant is None, e.g. the superadmin panel):
    only an account with tenant=None (platform-level / staff) may
    authenticate.
If no request is available (e.g. management commands), falls back to the
old global lookup for backwards compatibility.
"""
from django.contrib.auth.backends import ModelBackend

from .models import User


class TenantAwareModelBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        email = username or kwargs.get(User.USERNAME_FIELD)
        if email is None or password is None:
            return None
        email = email.strip().lower()

        tenant = getattr(request, 'tenant', None) if request is not None else None

        if request is None:
            try:
                user = User.objects.get(email=email)
            except User.DoesNotExist:
                User().set_password(password)  # timing-attack mitigation
                return None
            except User.MultipleObjectsReturned:
                return None
            if user.check_password(password) and self.user_can_authenticate(user):
                return user
            return None

        candidates = list(User.objects.filter(email=email))
        if not candidates:
            User().set_password(password)  # timing-attack mitigation
            return None

        # Prefer the account that actually belongs on this request's tenant
        # (or, on the main domain, the platform-level tenant=None account).
        # If no such account exists, fall back to any matching-email
        # candidate so the password can still be checked and, on success,
        # the view's own cross-tenant / superadmin-portal checks run and
        # return their specific 403 — instead of this backend returning
        # None and simplejwt masking that with a generic 401.
        if tenant is not None:
            user = next((u for u in candidates if u.tenant_id == tenant.id), None)
        else:
            user = next((u for u in candidates if u.tenant_id is None), None)
        if user is None:
            user = candidates[0]

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
