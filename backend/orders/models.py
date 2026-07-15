from django.db import models
from bizal.base_models import TenantScopedUUIDModel, UUIDModel


class Order(TenantScopedUUIDModel):
    STATUS_CHOICES = [
        ('pending',    'Pending'),
        ('confirmed',  'Confirmed'),
        ('preparing',  'Preparing'),
        ('ready',      'Ready'),
        ('delivered',  'Delivered'),
        ('cancelled',  'Cancelled'),
    ]
    ORDER_TYPE_CHOICES = [
        ('dine_in',  'Dine In'),
        ('takeaway', 'Takeaway'),
        ('delivery', 'Delivery'),
    ]

    # lazy string refs (matching every other app's models.py) instead of
    # hard imports — avoids the risk of circular imports if menu/accounts
    # ever need to import from orders.
    user         = models.ForeignKey('accounts.User', null=True, blank=True, on_delete=models.SET_NULL)
    guest_name   = models.CharField(max_length=100, blank=True)
    guest_phone  = models.CharField(max_length=30, blank=True)
    order_type   = models.CharField(max_length=20, choices=ORDER_TYPE_CHOICES, default='dine_in')
    table_number      = models.CharField(max_length=10, blank=True)
    delivery_address  = models.CharField(max_length=300, blank=True)
    status       = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    notes        = models.TextField(blank=True)
    total_price  = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    class Meta:
        ordering = ['-created_at']

    def recalculate_total(self):
        self.total_price = sum(item.subtotal for item in self.items.all())
        self.save(update_fields=['total_price'])


class OrderItem(UUIDModel):
    # NOTE: OrderItem intentionally has no direct tenant FK. It is always
    # accessed through its Order parent (order__tenant), which provides the
    # tenant scope. If cross-order item analytics are ever needed (e.g.
    # "top-selling menu items platform-wide"), join through order__tenant
    # rather than adding a denormalised FK here.
    order     = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    menu_item = models.ForeignKey(
        'menu.MenuItem', on_delete=models.PROTECT, null=True, blank=True,
    )
    # Added so shop-type tenants (market, pharmacy, electronics, clothing,
    # organic, furniture, petrol_station, import_export, agro) can place
    # cash "porosi"-style orders through the same Order/OrderItem pipeline
    # food tenants already use, instead of a separate parallel system.
    # Exactly one of menu_item/product must be set — enforced by the
    # CheckConstraint below (mirrors how the rest of this codebase enforces
    # "exactly one of X/Y" invariants at the DB level, not just in the
    # serializer, so direct ORM usage can't create an invalid row either).
    product = models.ForeignKey(
        'inventory.Product', on_delete=models.PROTECT, null=True, blank=True,
        related_name='order_items',
    )
    quantity  = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)  # snapshot at order time
    notes     = models.CharField(max_length=200, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(menu_item__isnull=False, product__isnull=True) |
                    models.Q(menu_item__isnull=True, product__isnull=False)
                ),
                name='orderitem_exactly_one_of_menu_item_or_product',
            ),
        ]

    @property
    def subtotal(self):
        return self.unit_price * self.quantity

    @property
    def item_name(self):
        if self.menu_item_id:
            return self.menu_item.name
        if self.product_id:
            return self.product.name
        return ''