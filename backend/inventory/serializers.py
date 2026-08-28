from rest_framework import serializers
from .models import ProductCategory, Product


class ProductCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductCategory
        fields = ('id', 'name', 'slug', 'image')


class ProductSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    in_stock = serializers.BooleanField(read_only=True)
    is_low_stock = serializers.BooleanField(read_only=True)

    class Meta:
        model = Product
        fields = ('id', 'name', 'description', 'sku', 'price', 'stock', 'low_stock_threshold',
                  'in_stock', 'is_low_stock', 'image', 'is_active', 'is_featured',
                  'category', 'category_name')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # IDOR fix: scope the category FK to the current tenant so a tenant
        # owner cannot attach a product to another tenant's category by
        # supplying a foreign UUID. Without this, ProductManageView /
        # ProductUpdateView (IsTenantOwner) would accept the write silently.
        request = self.context.get('request')
        if request and hasattr(request, 'tenant') and request.tenant:
            self.fields['category'].queryset = ProductCategory.objects.filter(
                tenant=request.tenant
            )
        self.fields['category'].required = False
        self.fields['category'].allow_null = True
