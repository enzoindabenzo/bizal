from django.db import transaction
from rest_framework import generics, filters
from rest_framework.permissions import AllowAny
from django.db.models import F
from tenants.permissions import IsTenantOwner, HasTenantFeature
from tenants.limits import enforce_max_listings
from .models import ProductCategory, Product
from .serializers import ProductCategorySerializer, ProductSerializer

# Product/category management requires the tenant's plan to include
# 'inventory' (public read stays open).
INVENTORY_FEATURE = HasTenantFeature('inventory')


class ProductCategoryListView(generics.ListCreateAPIView):
    serializer_class = ProductCategorySerializer

    def get_permissions(self):
        if self.request.method == 'GET':
            return [AllowAny()]
        return [IsTenantOwner(), INVENTORY_FEATURE()]

    def get_queryset(self):
        return ProductCategory.objects.filter(tenant=self.request.tenant)

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)


class ProductCategoryDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET    /api/inventory/categories/<pk>/ — public
    PUT/PATCH/DELETE — owner only
    """
    serializer_class = ProductCategorySerializer

    def get_permissions(self):
        if self.request.method == 'GET':
            return [AllowAny()]
        return [IsTenantOwner(), INVENTORY_FEATURE()]

    def get_queryset(self):
        return ProductCategory.objects.filter(tenant=self.request.tenant)


class ProductListView(generics.ListCreateAPIView):
    """
    GET  /api/inventory/ — public, only active products
    POST /api/inventory/ — owner only, creates a product

    NOTE: this view (plus ProductDetailView below) replaces what used to
    be three separate endpoints — a public list-only view here, a
    create-only `/create/` view, and a separate `/<pk>/manage/`
    retrieve-update-destroy view — for no behavioral reason beyond how
    they were originally split up. That split also meant the tenant admin
    UI (which calls POST /inventory/ and PATCH/DELETE /inventory/<id>/
    directly, matching every other resource's URL convention in this
    codebase) was silently hitting 405 Method Not Allowed, since this view
    only supported GET. Consolidated to the same ListCreateAPIView +
    RetrieveUpdateDestroyAPIView pattern used by every other app.
    `/create/` and `/<pk>/manage/` are kept as aliases (see urls.py) purely
    for backward compatibility with existing callers/tests — no new code
    should target them.
    """
    serializer_class = ProductSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ['name', 'description', 'sku']

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsTenantOwner(), INVENTORY_FEATURE()]
        return [AllowAny()]

    def get_queryset(self):
        # Owner-authenticated POST doesn't read this queryset, but GET
        # (public) must only ever see active products.
        qs = Product.objects.filter(tenant=self.request.tenant, is_active=True)
        category = self.request.query_params.get('category')
        featured = self.request.query_params.get('featured')
        if category:
            qs = qs.filter(category__slug=category)
        if featured:
            qs = qs.filter(is_featured=True)
        low_stock = self.request.query_params.get('low_stock')
        if low_stock:
            try:
                threshold = int(low_stock)
                qs = qs.filter(stock__lte=threshold)
            except (ValueError, TypeError):
                # No valid override threshold given — fall back to each
                # product's own persisted low_stock_threshold (default 5)
                # rather than forcing a single platform-wide number.
                qs = qs.filter(stock__lte=F('low_stock_threshold'))
        return qs

    def perform_create(self, serializer):
        with transaction.atomic():
            enforce_max_listings(self.request.tenant, Product)
            serializer.save(tenant=self.request.tenant)


class ProductDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET                 /api/inventory/<pk>/ — public, only active products
    PUT/PATCH/DELETE    /api/inventory/<pk>/ — owner only, any product
    (including inactive ones, so an owner can re-activate a deactivated
    product or fix one they just hid)
    """
    serializer_class = ProductSerializer

    def get_permissions(self):
        if self.request.method == 'GET':
            return [AllowAny()]
        return [IsTenantOwner(), INVENTORY_FEATURE()]

    def get_queryset(self):
        qs = Product.objects.filter(tenant=self.request.tenant)
        if self.request.method == 'GET':
            qs = qs.filter(is_active=True)
        return qs


# ── Backward-compatible aliases ─────────────────────────────────────────────
# Kept so existing callers/tests targeting /create/ and /<pk>/manage/
# continue to work unchanged. New code should use the consolidated
# endpoints above instead.
ProductManageView = ProductListView
ProductUpdateView = ProductDetailView


from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status as drf_status


@api_view(['POST'])
@permission_classes([IsTenantOwner])
def product_stock_adjust(request, pk):
    """
    POST /api/inventory/<pk>/stock/
    Body: { "delta": -3, "reason": "sold" }
           { "delta": 50, "reason": "restock" }

    Atomically adjusts Product.stock by `delta` (positive = restock,
    negative = sell/consume). Rejects if the result would go below zero.
    Uses select_for_update() so concurrent POS requests don't race.

    Reasons: "sold", "restock", "adjustment", "damaged", "returned"
    """
    try:
        product = Product.objects.get(pk=pk, tenant=request.tenant)
    except Product.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=drf_status.HTTP_404_NOT_FOUND)

    raw_delta = request.data.get('delta')
    reason = request.data.get('reason', 'adjustment')

    try:
        delta = int(raw_delta)
    except (TypeError, ValueError):
        return Response({'detail': '`delta` must be an integer.'}, status=drf_status.HTTP_400_BAD_REQUEST)

    if delta == 0:
        return Response({'detail': '`delta` must be non-zero.'}, status=drf_status.HTTP_400_BAD_REQUEST)

    with transaction.atomic():
        # L-4 FIX: add tenant= filter for defence-in-depth; mirrors the outer check.
        locked = Product.objects.select_for_update().get(pk=pk, tenant=request.tenant)
        new_stock = locked.stock + delta
        if new_stock < 0:
            return Response(
                {'detail': f'Insufficient stock: current {locked.stock}, requested delta {delta}.'},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )
        Product.objects.filter(pk=pk).update(stock=F('stock') + delta)
        locked.refresh_from_db(fields=['stock'])

    try:
        from activity.utils import log_activity
        log_activity(
            tenant=request.tenant,
            actor=request.user,
            verb='inventory.stock_adjusted',
            description=f'{product.name}: {("+" if delta > 0 else "")}{delta} ({reason}). New stock: {locked.stock}.',
            target_type='product',
            target_id=product.id,
            metadata={'delta': delta, 'reason': reason, 'new_stock': locked.stock},
        )
    except Exception:
        pass  # activity log failure must never block stock adjustment

    return Response({'id': str(product.pk), 'stock': locked.stock, 'delta': delta, 'reason': reason})
