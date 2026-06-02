from rest_framework import serializers, generics
from rest_framework.permissions import AllowAny
from tenants.permissions import IsTenantOwner
from .models import MenuCategory, MenuItem


class MenuItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = MenuItem
        fields = ('id', 'name', 'description', 'price', 'image', 'is_available',
                  'is_featured', 'allergens', 'calories', 'order')


class MenuCategorySerializer(serializers.ModelSerializer):
    items = MenuItemSerializer(many=True, read_only=True)

    class Meta:
        model = MenuCategory
        fields = ('id', 'name', 'description', 'order', 'items')


class MenuListView(generics.ListAPIView):
    serializer_class = MenuCategorySerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        return MenuCategory.objects.filter(
            tenant=self.request.tenant, is_active=True
        ).prefetch_related('items')


class MenuItemCreateView(generics.CreateAPIView):
    serializer_class = MenuItemSerializer
    permission_classes = [IsTenantOwner]

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)


class MenuItemUpdateView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = MenuItemSerializer
    permission_classes = [IsTenantOwner]

    def get_queryset(self):
        return MenuItem.objects.filter(tenant=self.request.tenant)
