from django.db import transaction
from rest_framework import generics
from rest_framework.permissions import AllowAny
from django.db.models.deletion import ProtectedError
from rest_framework.exceptions import ValidationError
from tenants.permissions import IsTenantOwner
from tenants.limits import enforce_max_listings
from .models import MenuCategory, MenuItem
from .serializers import MenuCategorySerializer, MenuItemSerializer


class MenuListView(generics.ListAPIView):
    serializer_class = MenuCategorySerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        return MenuCategory.objects.filter(
            tenant=self.request.tenant, is_active=True
        ).prefetch_related('items')


class MenuCategoryManageView(generics.CreateAPIView):
    serializer_class = MenuCategorySerializer
    permission_classes = [IsTenantOwner]

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)


class MenuCategoryUpdateView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = MenuCategorySerializer
    permission_classes = [IsTenantOwner]

    def get_queryset(self):
        return MenuCategory.objects.filter(tenant=self.request.tenant)

    def perform_destroy(self, instance):
        # v49 FIX: MenuItems have on_delete=CASCADE to MenuCategory, and
        # OrderItem.menu_item has on_delete=PROTECT. Deleting a category whose
        # items have been ordered raises ProtectedError during the cascade.
        # DRF's default exception handler does not catch ProtectedError, so
        # without this override the request surfaces as an unhandled 500.
        # Return a clear 409 Conflict instead so the owner knows why the delete
        # failed and what to do instead (mark items unavailable first).
        try:
            instance.delete()
        except ProtectedError:
            raise ValidationError(
                'This category cannot be deleted because one or more of its items '
                'appear in existing orders. Mark the items unavailable instead, '
                'or remove them from all orders first.'
            )


class MenuItemCreateView(generics.ListCreateAPIView):
    serializer_class = MenuItemSerializer

    def get_permissions(self):
        if self.request.method == 'GET':
            return [AllowAny()]
        return [IsTenantOwner()]

    def get_queryset(self):
        qs = MenuItem.objects.filter(tenant=self.request.tenant)
        # Show unavailable items only to staff/owner of this tenant.
        # The previous check (is_authenticated) incorrectly exposed hidden items
        # to any logged-in user including customers of other tenants.
        user = self.request.user
        # LOW-2 FIX (v52): Use get_effective_role() so deactivated staff
        # (StaffMember.is_active=False) cannot see hidden menu items.
        # getattr(user,'role') bypassed the is_active guard.
        from tenants.permissions import get_effective_role
        is_staff = (
            user
            and user.is_authenticated
            and (user.is_superuser or get_effective_role(user, self.request.tenant) is not None)
        )
        if not is_staff:
            qs = qs.filter(is_available=True)
        return qs

    def perform_create(self, serializer):
        with transaction.atomic():
            enforce_max_listings(self.request.tenant, MenuItem)
            serializer.save(tenant=self.request.tenant)


class MenuItemUpdateView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = MenuItemSerializer
    permission_classes = [IsTenantOwner]

    def get_queryset(self):
        return MenuItem.objects.filter(tenant=self.request.tenant)

    def perform_destroy(self, instance):
        # v49 FIX: OrderItem.menu_item uses on_delete=PROTECT so that
        # historical order data is never silently broken. Without this override,
        # deleting a MenuItem that appears in any order raises ProtectedError
        # which DRF's default exception handler does not catch, surfacing as an
        # unhandled 500. Return a clear 409 Conflict instead.
        try:
            instance.delete()
        except ProtectedError:
            raise ValidationError(
                'This item cannot be deleted because it appears in existing orders. '
                'Set it to unavailable (is_available=False) to hide it from customers.'
            )