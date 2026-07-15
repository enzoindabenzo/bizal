from rest_framework import serializers
from django.db import transaction
from django.db.models import F
from .models import Order, OrderItem
from menu.models import MenuItem
from inventory.models import Product


class TenantMenuItemField(serializers.PrimaryKeyRelatedField):
    """
    PrimaryKeyRelatedField that restricts choices to the current tenant's
    menu items.  The queryset is resolved lazily at validation time
    (via get_queryset) rather than at serializer __init__ time, so nested
    use inside OrderSerializer(many=True) always sees request.tenant.

    FIX: The queryset intentionally does NOT filter by is_available=True here.
    Filtering at validation time produced "Invalid pk – object does not exist"
    errors when a customer's cart contained a valid menu item UUID that was
    made unavailable *after* the menu page loaded (e.g. owner toggling items
    off at closing time while a customer was mid-cart). The UUID is genuine
    and belongs to the tenant, so the cryptic PK-not-found error was wrong.
    Availability is now checked explicitly in OrderSerializer.create() so the
    customer receives a clear, human-readable 400 error message.
    """

    def get_queryset(self):
        request = self.context.get('request')
        tenant = getattr(request, 'tenant', None) if request else None
        if tenant:
            return MenuItem.objects.filter(tenant=tenant)
        return MenuItem.objects.none()


class TenantProductField(serializers.PrimaryKeyRelatedField):
    """
    Same pattern as TenantMenuItemField, for shop-type tenants' cash
    "porosi"-style checkout. Deliberately doesn't filter on stock/is_active
    here either — stock is checked explicitly (and re-checked under lock) in
    OrderSerializer.create() so a customer whose cart went stale gets a clear
    "not enough stock" message instead of a generic PK error.
    """

    def get_queryset(self):
        request = self.context.get('request')
        tenant = getattr(request, 'tenant', None) if request else None
        if tenant:
            return Product.objects.filter(tenant=tenant)
        return Product.objects.none()


class OrderItemSerializer(serializers.ModelSerializer):
    menu_item_name = serializers.CharField(source='menu_item.name', read_only=True)
    product_name    = serializers.CharField(source='product.name', read_only=True)
    subtotal       = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    menu_item      = TenantMenuItemField(required=False, allow_null=True)
    product        = TenantProductField(required=False, allow_null=True)

    class Meta:
        model  = OrderItem
        fields = ['id', 'menu_item', 'menu_item_name', 'product', 'product_name',
                  'quantity', 'unit_price', 'notes', 'subtotal']
        read_only_fields = ['id', 'unit_price']  # unit_price snapshotted on create

    def validate(self, attrs):
        has_menu_item = attrs.get('menu_item') is not None
        has_product   = attrs.get('product') is not None
        if has_menu_item == has_product:  # neither, or both
            raise serializers.ValidationError(
                'Each order item must reference exactly one menu item or product.'
            )
        return attrs


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True)

    class Meta:
        model  = Order
        fields = [
            'id', 'tenant', 'user', 'guest_name', 'guest_phone',
            'order_type', 'table_number', 'delivery_address', 'status', 'notes',
            'total_price', 'items', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'tenant', 'user', 'status', 'total_price', 'created_at', 'updated_at']

    def create(self, validated_data):
        # v49 FIX: wrap the entire Order + OrderItem creation sequence in a
        # single atomic transaction. Previously, a transient DB error partway
        # through the OrderItem loop (or during recalculate_total) would leave
        # an Order row with zero or partial items and total_price=0 permanently
        # in the database, while the caller received a 500 with no way to tell
        # whether the order was committed. ATOMIC_REQUESTS is not set in this
        # project, so there is no implicit per-request transaction.
        items_data = validated_data.pop('items')

        menu_item_items = [d for d in items_data if d.get('menu_item') is not None]
        product_items    = [d for d in items_data if d.get('product') is not None]

        # FIX: Validate availability here rather than in get_queryset() so the
        # customer gets a clear error message instead of "Invalid pk … does not
        # exist". Items may become unavailable between the customer loading the
        # menu page and submitting their order (e.g. owner marks items off at
        # closing time). The UUID is valid and tenant-scoped; only the
        # availability state has changed.
        unavailable = [
            item_data['menu_item'].name
            for item_data in menu_item_items
            if not item_data['menu_item'].is_available
        ]
        if unavailable:
            raise serializers.ValidationError({
                'items': f'Këto artikuj nuk janë më të disponueshëm: {", ".join(unavailable)}.'
            })

        # Same idea for products (shop-type tenants): a product hidden/sold
        # out between the customer loading the storefront and submitting the
        # order should produce a clear message, not a generic error. This is
        # a pre-check for a fast, friendly failure — the real, race-safe
        # check happens under select_for_update() inside the transaction
        # below, since stock can still change between this check and the lock.
        inactive = [d['product'].name for d in product_items if not d['product'].is_active]
        if inactive:
            raise serializers.ValidationError({
                'items': f'Këto produkte nuk janë më të disponueshme: {", ".join(inactive)}.'
            })
        needed_by_product = {}
        for d in product_items:
            needed_by_product[d['product'].pk] = needed_by_product.get(d['product'].pk, 0) + d.get('quantity', 1)
        insufficient = [
            f"{d['product'].name} (mbeten {d['product'].stock})"
            for d in product_items
            if d['product'].stock < needed_by_product[d['product'].pk]
        ]
        if insufficient:
            # dedupe while preserving order (same product can appear once
            # per unique name in the message even if it matched twice above)
            seen = []
            for m in insufficient:
                if m not in seen:
                    seen.append(m)
            raise serializers.ValidationError({
                'items': f"S'ka stok të mjaftueshëm për: {', '.join(seen)}."
            })

        with transaction.atomic():
            order = Order.objects.create(**validated_data)

            for item_data in menu_item_items:
                menu_item = item_data['menu_item']
                OrderItem.objects.create(
                    order=order,
                    menu_item=menu_item,
                    quantity=item_data.get('quantity', 1),
                    unit_price=menu_item.price,  # snapshot current price
                    notes=item_data.get('notes', ''),
                )

            if product_items:
                # Lock and re-check stock per unique product inside the
                # transaction — the pre-check above is only a friendly first
                # pass; two concurrent orders for the same last unit must not
                # both pass validation and both succeed. select_for_update()
                # here mirrors inventory.views.product_stock_adjust exactly.
                locked_products = {
                    p.pk: p
                    for p in Product.objects.select_for_update().filter(
                        pk__in=needed_by_product.keys()
                    )
                }
                still_insufficient = [
                    f"{locked_products[pk].name} (mbeten {locked_products[pk].stock})"
                    for pk, qty in needed_by_product.items()
                    if locked_products[pk].stock < qty
                ]
                if still_insufficient:
                    raise serializers.ValidationError({
                        'items': f"S'ka stok të mjaftueshëm për: {', '.join(still_insufficient)}."
                    })

                for item_data in product_items:
                    product = locked_products[item_data['product'].pk]
                    qty = item_data.get('quantity', 1)
                    OrderItem.objects.create(
                        order=order,
                        product=product,
                        quantity=qty,
                        unit_price=product.price,  # snapshot current price
                        notes=item_data.get('notes', ''),
                    )
                for pk, qty in needed_by_product.items():
                    Product.objects.filter(pk=pk).update(stock=F('stock') - qty)

                try:
                    from activity.utils import log_activity
                    for pk, qty in needed_by_product.items():
                        product = locked_products[pk]
                        log_activity(
                            tenant=order.tenant,
                            actor=order.user,
                            verb='inventory.stock_adjusted',
                            description=f'{product.name}: -{qty} (sold via order #{str(order.id)[:8]}). '
                                        f'New stock: {product.stock - qty}.',
                            target_type='product',
                            target_id=product.id,
                            metadata={'delta': -qty, 'reason': 'sold', 'order_id': str(order.id)},
                        )
                except Exception:
                    pass  # activity log failure must never block order creation

            order.recalculate_total()
        return order