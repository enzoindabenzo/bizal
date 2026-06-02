from rest_framework import serializers, generics
from rest_framework.permissions import AllowAny
from tenants.permissions import IsTenantOwner
from .models import ProductCategory, Product


class ProductCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductCategory
        fields = ('id', 'name', 'slug', 'image')


class ProductSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    in_stock = serializers.BooleanField(read_only=True)

    class Meta:
        model = Product
        fields = ('id', 'name', 'description', 'sku', 'price', 'stock', 'in_stock',
                  'image', 'is_active', 'is_featured', 'category', 'category_name')


class ProductListView(generics.ListAPIView):
    serializer_class = ProductSerializer
    permission_classes = [AllowAny]
    search_fields = ['name', 'description', 'sku']

    def get_queryset(self):
        qs = Product.objects.filter(tenant=self.request.tenant, is_active=True)
        category = self.request.query_params.get('category')
        featured = self.request.query_params.get('featured')
        if category:
            qs = qs.filter(category__slug=category)
        if featured:
            qs = qs.filter(is_featured=True)
        return qs


class ProductDetailView(generics.RetrieveAPIView):
    serializer_class = ProductSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        return Product.objects.filter(tenant=self.request.tenant, is_active=True)


class ProductManageView(generics.CreateAPIView):
    serializer_class = ProductSerializer
    permission_classes = [IsTenantOwner]

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)


class ProductUpdateView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ProductSerializer
    permission_classes = [IsTenantOwner]

    def get_queryset(self):
        return Product.objects.filter(tenant=self.request.tenant)
