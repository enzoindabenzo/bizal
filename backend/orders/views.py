import logging

from django.db import transaction
from django.db.models import F
from rest_framework import generics
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from tenants.permissions import HasTenantRole, get_effective_role
from .models import Order
from .serializers import OrderSerializer
from inventory.models import Product
from notifications.tasks import notify_owner_async
from billing.loyalty import award_points

logger = logging.getLogger(__name__)

# MEDIUM-2 FIX (v52): Transition guard mirrors the HIGH-1 bookings fix.
# admin_update_order previously accepted any valid status as new_status with no
# check on whether the transition from the current status is logically permitted.
# This allowed terminal states (delivered, cancelled) to be re-opened, creating
# ghost orders, inconsistent audit logs, and potential duplicate notifications.
# The award_points idempotency guard prevents double-crediting, but data integrity
# still breaks if a cancelled order can be moved back to confirmed/preparing.
_ORDER_STATUS_CHOICES = {s[0] for s in Order.STATUS_CHOICES}

ORDER_VALID_TRANSITIONS = {
    'pending':   {'confirmed', 'preparing', 'delivered', 'cancelled'},
    'confirmed': {'preparing', 'delivered', 'cancelled'},
    'preparing': {'ready', 'delivered', 'cancelled'},
    'ready':     {'delivered', 'cancelled'},
    'delivered': set(),   # terminal — no outbound transitions
    'cancelled': set(),   # terminal — no outbound transitions
}


class OrderListCreateView(generics.ListCreateAPIView):
    serializer_class = OrderSerializer

    def get_permissions(self):
        if self.request.method == 'POST':
            return [AllowAny()]
        return [IsAuthenticated()]

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return Order.objects.none()
        # L-3 FIX: Short-circuit to none() on the main domain (tenant=None).
        # Without this, filter(tenant=None) issues a valid but semantically
        # wrong DB query. Any logged-in platform superadmin on the main domain
        # would receive an empty list rather than a clear signal that this
        # endpoint is tenant-scoped only.
        if self.request.tenant is None:
            return Order.objects.none()
        qs = Order.objects.filter(tenant=self.request.tenant).prefetch_related('items__menu_item', 'items__product')
        # LOW-3 FIX: Use get_effective_role() — respects StaffMember.is_active.
        if not (user.is_superuser or get_effective_role(user, self.request.tenant) is not None):
            qs = qs.filter(user=user)
        return qs

    def perform_create(self, serializer):
        user = self.request.user if self.request.user.is_authenticated else None
        # MED-6 FIX: Reject unauthenticated POST from the main domain where
        # request.tenant is None. The serializer would propagate tenant=None
        # straight to the DB, triggering an IntegrityError (NOT NULL violation)
        # which Django surfaces as a 500 rather than a 400. Fail fast here with
        # a clear 400 so the error is client-visible and doesn't spam Sentry.
        from rest_framework.exceptions import ValidationError
        if self.request.tenant is None:
            raise ValidationError({'detail': 'Orders must be placed on a tenant subdomain.'})
        # MED-1 FIX REVERTED: The original gate blocked ALL order creation for
        # tenants without the 'payments' feature. This was wrong — order *taking*
        # (including cash, dine-in, and takeaway) is a core feature that any food
        # business needs regardless of plan. The 'payments' feature flag governs
        # online Stripe payment processing, which is handled separately in the
        # payments app. Blocking cash orders behind a Pro/Enterprise paywall meant
        # restaurants on Trial or Pro plans could not receive any orders at all.
        order = serializer.save(tenant=self.request.tenant, user=user)
        if self.request.tenant:
            # Dispatched async so the DB query for owner/manager users
            # doesn't block the HTTP response (mirrors bookings fix).
            guest = order.guest_name or (user.display_name if user else 'Guest')
            notify_owner_async.delay(
                str(self.request.tenant.pk),
                'order_placed',
                'New Order',
                f'{guest} placed a {order.get_order_type_display()} order (#{str(order.id)[:8]}).',
                metadata={'order_id': str(order.id)},
                idempotency_key=f'order:{order.id}',
            )


class OrderDetailView(generics.RetrieveAPIView):
    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Order.objects.filter(tenant=self.request.tenant).prefetch_related('items__menu_item', 'items__product')
        user = self.request.user
        # Staff/owner/manager see all orders; customers only their own
        # LOW-3 FIX: Use get_effective_role() — respects StaffMember.is_active.
        if not (user.is_superuser or get_effective_role(user, self.request.tenant) is not None):
            qs = qs.filter(user=user)
        return qs


@api_view(['PATCH'])
@permission_classes([HasTenantRole('staff', 'receptionist')])
def admin_update_order(request, pk):
    try:
        order = Order.objects.get(pk=pk, tenant=request.tenant)
    except Order.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=404)

    update_fields = []
    new_status = None  # CRIT-1 FIX: initialize before conditional so line 95 never raises NameError

    if 'status' in request.data:
        new_status = request.data.get('status')
        valid_statuses = [s[0] for s in Order.STATUS_CHOICES]
        if new_status not in valid_statuses:
            return Response(
                {'detail': f'Invalid status. Choices: {valid_statuses}'},
                status=400,
            )
        # MEDIUM-2 FIX (v52): Enforce allowed transitions.
        allowed = ORDER_VALID_TRANSITIONS.get(order.status, set())
        if new_status not in allowed:
            return Response(
                {'detail': f'Cannot transition order from "{order.status}" to "{new_status}".'},
                status=400,
            )
        order.status = new_status
        update_fields.append('status')

    # Staff-editable fields beyond status. Previously there was no way to
    # correct these after order creation (e.g. a guest_name typo, or a
    # table reassignment) without going around the API.
    if 'notes' in request.data:
        order.notes = request.data.get('notes') or ''
        update_fields.append('notes')
    if 'table_number' in request.data:
        order.table_number = request.data.get('table_number') or ''
        update_fields.append('table_number')
    if 'guest_name' in request.data:
        order.guest_name = request.data.get('guest_name') or ''
        update_fields.append('guest_name')

    if not update_fields:
        # LOW-1 FIX: nothing was supplied — return current state without a pointless DB write
        return Response(OrderSerializer(order).data)

    update_fields.append('updated_at')  # MEDIUM-3 FIX: always bump updated_at on any field change

    with transaction.atomic():
        order.save(update_fields=update_fields)

        if new_status == 'delivered':  # HIGH-3 FIX: check transition, not current status
            # MED-2 FIX: Mirror the bookings loyalty log pattern.
            # total_price has default=0 (never None). Award points only when there
            # is a registered user and a positive price. Free orders (price=0) and
            # guest orders (user=None) are valid — log guest+paid so operators can
            # diagnose "my points didn't accrue" reports without guessing the cause.
            if order.user_id and order.total_price > 0:
                award_points(
                    request.tenant, order.user, order.total_price,
                    reason=f'Order #{str(order.id)[:8]}',
                    source_type='order', source_id=order.id,
                )
            elif not order.user_id and order.total_price > 0:
                logger.info(
                    'award_points skipped for order %s: guest order (no user account), price=%s',
                    order.id, order.total_price,
                )
            # total_price == 0: free/complimentary order — no points expected, no log needed

        if new_status == 'cancelled':
            # Stock for product-based items was already decremented at order
            # creation time (see OrderSerializer.create()). Cancelling the
            # order means the sale didn't go through, so that stock needs to
            # go back — otherwise every cancelled order permanently loses
            # units from inventory. select_for_update() mirrors the same
            # locking pattern used everywhere else stock is touched.
            product_items = list(
                order.items.select_related('product').filter(product__isnull=False)
            )
            if product_items:
                product_ids = [pi.product_id for pi in product_items]
                locked = {
                    p.pk: p for p in Product.objects.select_for_update().filter(pk__in=product_ids)
                }
                for pi in product_items:
                    product = locked.get(pi.product_id)
                    if not product:
                        continue  # product was deleted since — nothing to restock
                    Product.objects.filter(pk=pi.product_id).update(stock=F('stock') + pi.quantity)
                try:
                    from activity.utils import log_activity
                    for pi in product_items:
                        product = locked.get(pi.product_id)
                        if not product:
                            continue
                        log_activity(
                            tenant=request.tenant,
                            actor=request.user,
                            verb='inventory.stock_adjusted',
                            description=f'{product.name}: +{pi.quantity} (order #{str(order.id)[:8]} cancelled). '
                                        f'New stock: {product.stock + pi.quantity}.',
                            target_type='product',
                            target_id=product.id,
                            metadata={'delta': pi.quantity, 'reason': 'returned', 'order_id': str(order.id)},
                        )
                except Exception:
                    pass  # activity log failure must never block cancellation

    return Response(OrderSerializer(order).data)