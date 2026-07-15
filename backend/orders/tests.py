from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from tenants.models import Tenant
from menu.models import MenuCategory, MenuItem
from inventory.models import Product
from orders.models import Order, OrderItem


def make_tenant(slug='diner', **kwargs):
    defaults = dict(
        name='Test Diner', slug=slug, business_type='restaurant',
        plan='pro', is_active=True,
    )
    defaults.update(kwargs)
    return Tenant.objects.create(**defaults)


def make_user(email, tenant, role='customer', **kwargs):
    return User.objects.create_user(email=email, password='pass1234', tenant=tenant, role=role, **kwargs)


class OrderModelTests(TestCase):
    def setUp(self):
        self.tenant = make_tenant()
        self.category = MenuCategory.objects.create(tenant=self.tenant, name='Mains')
        self.item = MenuItem.objects.create(
            tenant=self.tenant, category=self.category, name='Burger', price=Decimal('9.50'),
        )

    def test_subtotal_is_price_times_quantity(self):
        order = Order.objects.create(tenant=self.tenant, order_type='dine_in')
        line = OrderItem.objects.create(order=order, menu_item=self.item, quantity=3, unit_price=self.item.price)
        self.assertEqual(line.subtotal, Decimal('28.50'))

    def test_recalculate_total_sums_all_items(self):
        order = Order.objects.create(tenant=self.tenant, order_type='takeaway')
        OrderItem.objects.create(order=order, menu_item=self.item, quantity=2, unit_price=Decimal('9.50'))
        second = MenuItem.objects.create(tenant=self.tenant, category=self.category, name='Fries', price=Decimal('3.00'))
        OrderItem.objects.create(order=order, menu_item=second, quantity=1, unit_price=Decimal('3.00'))
        order.recalculate_total()
        self.assertEqual(order.total_price, Decimal('22.00'))

    def test_unit_price_is_a_snapshot_not_live(self):
        """Changing the menu item's price later shouldn't affect past orders."""
        order = Order.objects.create(tenant=self.tenant, order_type='dine_in')
        line = OrderItem.objects.create(order=order, menu_item=self.item, quantity=1, unit_price=self.item.price)
        self.item.price = Decimal('99.00')
        self.item.save(update_fields=['price'])
        line.refresh_from_db()
        self.assertEqual(line.unit_price, Decimal('9.50'))


class OrderAPITests(TestCase):
    def setUp(self):
        self.tenant = make_tenant(slug='diner1')
        self.other_tenant = make_tenant(slug='diner2')
        self.category = MenuCategory.objects.create(tenant=self.tenant, name='Mains')
        self.item = MenuItem.objects.create(
            tenant=self.tenant, category=self.category, name='Pizza', price=Decimal('12.00'),
        )
        self.client = APIClient()
        self.client.defaults['HTTP_HOST'] = 'diner1.bizal.al'

    def test_guest_can_place_order(self):
        resp = self.client.post('/api/orders/', {
            'guest_name': 'Walk-in', 'guest_phone': '0691234567',
            'order_type': 'dine_in', 'table_number': '5',
            'items': [{'menu_item': str(self.item.id), 'quantity': 2}],
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        order = Order.objects.get(guest_name='Walk-in')
        self.assertEqual(order.tenant, self.tenant)
        self.assertEqual(order.total_price, Decimal('24.00'))
        self.assertIsNone(order.user)

    def test_snapshot_price_used_even_if_client_sends_different_unit_price(self):
        """unit_price is read_only on the serializer — a malicious client
        sending a lower price should be ignored in favor of the real
        MenuItem.price at order time."""
        resp = self.client.post('/api/orders/', {
            'guest_name': 'Sneaky', 'order_type': 'takeaway',
            'items': [{'menu_item': str(self.item.id), 'quantity': 1, 'unit_price': '0.01'}],
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        order = Order.objects.get(guest_name='Sneaky')
        self.assertEqual(order.items.first().unit_price, Decimal('12.00'))

    def test_logged_in_customer_sees_only_their_own_orders(self):
        cust1 = make_user('c1@x.com', self.tenant)
        cust2 = make_user('c2@x.com', self.tenant)
        Order.objects.create(tenant=self.tenant, user=cust1, order_type='dine_in')
        Order.objects.create(tenant=self.tenant, user=cust2, order_type='dine_in')

        self.client.force_authenticate(user=cust1)
        resp = self.client.get('/api/orders/')
        data = resp.data['results'] if 'results' in resp.data else resp.data
        self.assertEqual(len(data), 1)

    def test_staff_sees_all_tenant_orders(self):
        staff = make_user('staff@x.com', self.tenant, role='staff')
        from staff.models import StaffMember
        StaffMember.objects.create(tenant=self.tenant, user=staff, role='staff', is_active=True)
        cust = make_user('c1@x.com', self.tenant)
        Order.objects.create(tenant=self.tenant, user=cust, order_type='dine_in')
        Order.objects.create(tenant=self.tenant, order_type='takeaway', guest_name='Guest')

        self.client.force_authenticate(user=staff)
        resp = self.client.get('/api/orders/')
        data = resp.data['results'] if 'results' in resp.data else resp.data
        self.assertEqual(len(data), 2)

    def test_orders_are_tenant_isolated(self):
        """An order placed on diner1 must never be visible from diner2's portal."""
        Order.objects.create(tenant=self.tenant, order_type='dine_in', guest_name='Diner1 Guest')

        other_client = APIClient()
        other_client.defaults['HTTP_HOST'] = 'diner2.bizal.al'
        owner2 = make_user('o2@x.com', self.other_tenant, role='owner')
        other_client.force_authenticate(user=owner2)
        resp = other_client.get('/api/orders/')
        data = resp.data['results'] if 'results' in resp.data else resp.data
        self.assertEqual(len(data), 0)

    def test_owner_can_update_order_status(self):
        owner = make_user('owner@x.com', self.tenant, role='owner')
        order = Order.objects.create(tenant=self.tenant, order_type='dine_in', guest_name='G')
        self.client.force_authenticate(user=owner)
        resp = self.client.patch(f'/api/orders/{order.id}/admin-update/', {'status': 'preparing'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        order.refresh_from_db()
        self.assertEqual(order.status, 'preparing')

    def test_customer_cannot_update_order_status(self):
        cust = make_user('c@x.com', self.tenant)
        order = Order.objects.create(tenant=self.tenant, order_type='dine_in', guest_name='G')
        self.client.force_authenticate(user=cust)
        resp = self.client.patch(f'/api/orders/{order.id}/admin-update/', {'status': 'preparing'}, format='json')
        self.assertEqual(resp.status_code, 403)


class OrderDetailSecurityTest(TestCase):
    """OrderDetailView customer scoping (added in security audit)."""

    def setUp(self):
        self.tenant = make_tenant(slug='det-diner')
        self.category = MenuCategory.objects.create(tenant=self.tenant, name='Mains')
        self.cust1 = make_user('c1@det.com', self.tenant)
        self.cust2 = make_user('c2@det.com', self.tenant)
        self.client = APIClient()
        self.client.defaults['HTTP_HOST'] = 'det-diner.bizal.al'

    def test_customer_cannot_see_another_customers_order(self):
        """GET /orders/<pk>/ must return 404 for orders not belonging to the requester."""
        order = Order.objects.create(tenant=self.tenant, user=self.cust1, order_type='dine_in')
        self.client.force_authenticate(user=self.cust2)
        resp = self.client.get(f'/api/orders/{order.id}/')
        self.assertEqual(resp.status_code, 404)

    def test_owner_can_see_any_order(self):
        owner = make_user('o@det.com', self.tenant, role='owner')
        order = Order.objects.create(tenant=self.tenant, user=self.cust1, order_type='dine_in')
        self.client.force_authenticate(user=owner)
        resp = self.client.get(f'/api/orders/{order.id}/')
        self.assertEqual(resp.status_code, 200)

    def test_invalid_status_rejected(self):
        owner = make_user('owner2@det.com', self.tenant, role='owner')
        order = Order.objects.create(tenant=self.tenant, order_type='dine_in', guest_name='G')
        self.client.force_authenticate(user=owner)
        resp = self.client.patch(
            f'/api/orders/{order.id}/admin-update/', {'status': 'not_a_real_status'}
        )
        self.assertEqual(resp.status_code, 400)


class OrderNotifyAsyncTest(TestCase):
    """Placing an order must dispatch notify_owner_async.delay, not call
    notify_owner synchronously — the sync call blocks the HTTP response
    thread with a DB query to find owner/manager users."""

    def setUp(self):
        self.tenant = make_tenant(slug='notify-diner')
        self.category = MenuCategory.objects.create(tenant=self.tenant, name='Mains')
        self.item = MenuItem.objects.create(
            tenant=self.tenant, category=self.category, name='Pasta', price=Decimal('8.00'),
        )
        self.client = APIClient()
        self.client.defaults['HTTP_HOST'] = 'notify-diner.bizal.al'

    @patch('orders.views.notify_owner_async')
    def test_order_create_dispatches_async_notification(self, mock_task):
        """POST /api/orders/ must call notify_owner_async.delay, not the sync util."""
        resp = self.client.post('/api/orders/', {
            'guest_name': 'Test Guest',
            'order_type': 'takeaway',
            'items': [{'menu_item': str(self.item.id), 'quantity': 1}],
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        mock_task.delay.assert_called_once()
        args = mock_task.delay.call_args[0]
        self.assertEqual(args[0], str(self.tenant.pk))   # tenant_id
        self.assertEqual(args[1], 'order_placed')

    @patch('orders.views.notify_owner_async')
    def test_sync_notify_owner_is_not_called(self, mock_task):
        """Confirm the old synchronous path is gone."""
        with patch('notifications.utils.notify_owner') as mock_sync:
            self.client.post('/api/orders/', {
                'guest_name': 'Another Guest',
                'order_type': 'dine_in',
                'items': [{'menu_item': str(self.item.id), 'quantity': 1}],
            }, format='json')
            mock_sync.assert_not_called()


class OrderAdminUpdatePermissionTests(TestCase):
    """admin_update_order was IsTenantOwner-only, blocking kitchen/waitstaff
    (role='staff') from updating order status even though the admin UI's
    order board is shown to them with no role gating."""

    def setUp(self):
        self.tenant = make_tenant(slug='diner3')
        category = MenuCategory.objects.create(tenant=self.tenant, name='Mains')
        item = MenuItem.objects.create(tenant=self.tenant, category=category, name='Pizza', price=Decimal('12.00'))
        self.order = Order.objects.create(tenant=self.tenant, order_type='dine_in', guest_name='Walk-in')
        OrderItem.objects.create(order=self.order, menu_item=item, quantity=1, unit_price=Decimal('12.00'))
        self.client = APIClient()
        self.client.defaults['HTTP_HOST'] = 'diner3.bizal.al'

    def test_generic_staff_can_update_order_status(self):
        from staff.models import StaffMember
        waiter = make_user('waiter@diner3.com', self.tenant, role='customer')
        StaffMember.objects.create(tenant=self.tenant, user=waiter, role='staff', is_active=True)
        self.client.force_authenticate(user=waiter)
        resp = self.client.patch(f'/api/orders/{self.order.pk}/admin-update/', {'status': 'preparing'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'preparing')

    def test_customer_cannot_update_order_status(self):
        customer = make_user('cust@diner3.com', self.tenant, role='customer')
        self.client.force_authenticate(user=customer)
        resp = self.client.patch(f'/api/orders/{self.order.pk}/admin-update/', {'status': 'preparing'}, format='json')
        self.assertEqual(resp.status_code, 403)


class ProductOrderTests(TestCase):
    """Cash 'porosi'-style checkout for shop-type tenants (market, pharmacy,
    electronics, etc.), reusing the same Order/OrderItem pipeline food
    tenants use, but against inventory.Product with real atomic stock
    decrement instead of menu.MenuItem."""

    def setUp(self):
        self.tenant = make_tenant(slug='shop1', business_type='electronics')
        self.product = Product.objects.create(
            tenant=self.tenant, name='Headphones', price=Decimal('25.00'), stock=5,
        )
        self.client = APIClient()
        self.client.defaults['HTTP_HOST'] = 'shop1.bizal.al'

    def test_placing_order_decrements_stock(self):
        resp = self.client.post('/api/orders/', {
            'guest_name': 'Buyer', 'guest_phone': '0691234567', 'order_type': 'delivery',
            'delivery_address': 'Rr. Dëshmorët 12',
            'items': [{'product': str(self.product.id), 'quantity': 3}],
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 2)
        order = Order.objects.get(guest_name='Buyer')
        self.assertEqual(order.total_price, Decimal('75.00'))
        self.assertEqual(order.items.first().product_id, self.product.id)

    def test_cannot_order_more_than_available_stock(self):
        resp = self.client.post('/api/orders/', {
            'guest_name': 'Buyer', 'guest_phone': '0691234567', 'order_type': 'delivery',
            'delivery_address': 'Rr. Dëshmorët 12',
            'items': [{'product': str(self.product.id), 'quantity': 99}],
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 5)  # untouched

    def test_snapshot_price_used_even_if_client_sends_different_unit_price(self):
        resp = self.client.post('/api/orders/', {
            'guest_name': 'Sneaky', 'order_type': 'delivery', 'delivery_address': 'x',
            'items': [{'product': str(self.product.id), 'quantity': 1, 'unit_price': '0.01'}],
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        order = Order.objects.get(guest_name='Sneaky')
        self.assertEqual(order.items.first().unit_price, Decimal('25.00'))

    def test_cancelling_order_restores_stock(self):
        from staff.models import StaffMember
        owner = make_user('owner@shop1.com', self.tenant, role='owner')
        StaffMember.objects.create(tenant=self.tenant, user=owner, role='staff', is_active=True)

        order = Order.objects.create(tenant=self.tenant, order_type='delivery', guest_name='Buyer', status='pending')
        OrderItem.objects.create(order=order, product=self.product, quantity=3, unit_price=self.product.price)
        Product.objects.filter(pk=self.product.pk).update(stock=2)  # simulate the decrement that create() would have done

        self.client.force_authenticate(user=owner)
        resp = self.client.patch(f'/api/orders/{order.pk}/admin-update/', {'status': 'cancelled'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 5)  # restored

    def test_order_item_requires_exactly_one_of_menu_item_or_product(self):
        order = Order.objects.create(tenant=self.tenant, order_type='delivery')
        with self.assertRaises(Exception):
            OrderItem.objects.create(order=order, quantity=1, unit_price=Decimal('1.00'))
