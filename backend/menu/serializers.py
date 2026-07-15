from rest_framework import serializers
from .models import MenuCategory, MenuItem


class MenuItemSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)

    class Meta:
        model = MenuItem
        fields = ('id', 'category', 'category_name', 'name', 'description', 'price', 'image',
                  'is_available', 'is_featured', 'allergens', 'calories', 'order')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # IDOR fix: scope the category FK to the current tenant so a tenant
        # owner cannot attach a menu item to another tenant's category by
        # supplying a foreign UUID. Without this, MenuItemCreateView
        # (IsTenantOwner) would accept the write and corrupt the item's
        # category relationship silently.
        request = self.context.get('request')
        if request and hasattr(request, 'tenant') and request.tenant:
            self.fields['category'].queryset = MenuCategory.objects.filter(
                tenant=request.tenant
            )


class MenuCategorySerializer(serializers.ModelSerializer):
    items = serializers.SerializerMethodField()

    class Meta:
        model = MenuCategory
        fields = ('id', 'name', 'description', 'order', 'items')

    def get_items(self, obj):
        request = self.context.get('request')
        items = obj.items.all()
        # Show unavailable items only to staff/owner of this tenant.
        # The previous check (is_authenticated) incorrectly exposed hidden items
        # to any logged-in user, including customers of unrelated tenants.
        user = request.user if request else None
        # LOW-2 FIX (v52): Use get_effective_role() so deactivated staff
        # cannot see hidden menu items via the serializer's nested items list.
        from tenants.permissions import get_effective_role
        tenant = getattr(request, 'tenant', None) if request else None
        is_staff = (
            user
            and user.is_authenticated
            and (user.is_superuser or get_effective_role(user, tenant) is not None)
        )
        if not is_staff:
            items = items.filter(is_available=True)
        return MenuItemSerializer(items, many=True, context=self.context).data
