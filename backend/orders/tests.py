from decimal import Decimal

from unittest.mock import patch

from django.test import TestCase

from rest_framework.test import APIClient

from accounts.models import User

from tenants.models import Tenant

from menu.models import MenuCategory, MenuItem

from inventory.models import Product

from orders.models import Order, OrderItem

from tenants.models import Tenant, PLAN_ENTERPRISE

from inventory.models import Product, ProductCategory

from inventory.models import ProductCategory, Product

from orders.serializers import TenantMenuItemField, TenantProductField, OrderItemSerializer


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


class OrderListQuerysetEdgeCaseTests(TestCase):
    """Covers OrderListCreateView.get_queryset() lines 48 and 55."""

    def setUp(self):
        self.tenant = make_tenant(slug='qsdiner')
        self.client = APIClient()

    def test_unauthenticated_get_returns_empty(self):
        self.client.defaults['HTTP_HOST'] = 'qsdiner.bizal.al'
        resp = self.client.get('/api/orders/')
        self.assertEqual(resp.status_code, 401)  # IsAuthenticated blocks first

    def test_get_queryset_returns_none_for_unauthenticated_user_directly(self):
        # This branch is unreachable via the live HTTP endpoint (GET requires
        # IsAuthenticated, so an anonymous request 401s before get_queryset()
        # ever runs) but exists as defense-in-depth. Exercise it directly.
        from django.contrib.auth.models import AnonymousUser
        from django.test import RequestFactory
        from orders.views import OrderListCreateView

        rf = RequestFactory()
        django_request = rf.get('/api/orders/')
        django_request.user = AnonymousUser()
        django_request.tenant = self.tenant
        view = OrderListCreateView()
        view.request = view.initialize_request(django_request)
        view.request.user = AnonymousUser()
        self.assertEqual(view.get_queryset().count(), 0)

    def test_authenticated_superuser_on_main_domain_gets_empty_list(self):
        # request.tenant is None on the main domain -> short-circuits to none()
        # rather than issuing filter(tenant=None).
        admin = make_user('root@bizal.al', tenant=None, role='owner')
        admin.is_superuser = True
        admin.is_staff = True
        admin.save(update_fields=['is_superuser', 'is_staff'])
        self.client.defaults['HTTP_HOST'] = 'bizal.al'
        self.client.force_authenticate(user=admin)
        resp = self.client.get('/api/orders/')
        self.assertEqual(resp.status_code, 200)
        data = resp.data['results'] if 'results' in resp.data else resp.data
        self.assertEqual(len(data), 0)


class OrderCreateMainDomainRejectedTest(TestCase):
    """Covers perform_create()'s main-domain 400 guard (line 71)."""

    def test_post_on_main_domain_rejected_with_400(self):
        client = APIClient()
        client.defaults['HTTP_HOST'] = 'bizal.al'
        resp = client.post('/api/orders/', {
            'guest_name': 'Nobody', 'order_type': 'takeaway', 'items': [],
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('subdomain', str(resp.data))


class AdminUpdateOrderGapTests(TestCase):
    """Covers admin_update_order gaps: 404, field updates, empty PATCH,
    invalid transition, and the loyalty-award / restock-on-cancel branches."""

    def setUp(self):
        self.tenant = make_tenant(slug='admingaps')
        self.owner = make_user('owner@admingaps.com', self.tenant, role='owner')
        self.client = APIClient()
        self.client.defaults['HTTP_HOST'] = 'admingaps.bizal.al'
        self.client.force_authenticate(user=self.owner)

    def test_404_for_nonexistent_order(self):
        import uuid
        resp = self.client.patch(f'/api/orders/{uuid.uuid4()}/admin-update/', {'status': 'confirmed'}, format='json')
        self.assertEqual(resp.status_code, 404)

    def test_invalid_transition_from_terminal_status_rejected(self):
        order = Order.objects.create(tenant=self.tenant, order_type='dine_in', guest_name='G', status='delivered')
        resp = self.client.patch(f'/api/orders/{order.id}/admin-update/', {'status': 'preparing'}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Cannot transition', str(resp.data))

    def test_notes_table_number_and_guest_name_updated(self):
        order = Order.objects.create(tenant=self.tenant, order_type='dine_in', guest_name='Old Name')
        resp = self.client.patch(
            f'/api/orders/{order.id}/admin-update/',
            {'notes': 'extra spicy', 'table_number': '12', 'guest_name': 'New Name'},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        order.refresh_from_db()
        self.assertEqual(order.notes, 'extra spicy')
        self.assertEqual(order.table_number, '12')
        self.assertEqual(order.guest_name, 'New Name')

    def test_falsy_field_values_clear_to_empty_string(self):
        order = Order.objects.create(
            tenant=self.tenant, order_type='dine_in', guest_name='Someone',
            notes='old note', table_number='3',
        )
        resp = self.client.patch(
            f'/api/orders/{order.id}/admin-update/',
            {'notes': '', 'table_number': None, 'guest_name': ''},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        order.refresh_from_db()
        self.assertEqual(order.notes, '')
        self.assertEqual(order.table_number, '')
        self.assertEqual(order.guest_name, '')

    def test_empty_patch_returns_current_state_without_write(self):
        order = Order.objects.create(tenant=self.tenant, order_type='dine_in', guest_name='Untouched')
        resp = self.client.patch(f'/api/orders/{order.id}/admin-update/', {}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['guest_name'], 'Untouched')


class AdminUpdateOrderLoyaltyTests(TestCase):
    """Covers the award_points / guest-order-log branches on delivery (lines 165-176)."""

    def setUp(self):
        self.tenant = make_tenant(slug='loyaltydiner', plan=PLAN_ENTERPRISE)
        self.owner = make_user('owner@loyaltydiner.com', self.tenant, role='owner')
        self.customer = make_user('cust@loyaltydiner.com', self.tenant)
        self.client = APIClient()
        self.client.defaults['HTTP_HOST'] = 'loyaltydiner.bizal.al'
        self.client.force_authenticate(user=self.owner)

    @patch('orders.views.award_points')
    def test_delivering_paid_registered_order_awards_points(self, mock_award):
        order = Order.objects.create(
            tenant=self.tenant, user=self.customer, order_type='dine_in',
            status='confirmed', total_price=Decimal('20.00'),
        )
        resp = self.client.patch(f'/api/orders/{order.id}/admin-update/', {'status': 'delivered'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        mock_award.assert_called_once()
        _, kwargs = mock_award.call_args
        self.assertEqual(kwargs.get('source_type'), 'order') if kwargs else None

    @patch('orders.views.award_points')
    def test_delivering_free_registered_order_does_not_award_points(self, mock_award):
        order = Order.objects.create(
            tenant=self.tenant, user=self.customer, order_type='dine_in',
            status='confirmed', total_price=Decimal('0.00'),
        )
        resp = self.client.patch(f'/api/orders/{order.id}/admin-update/', {'status': 'delivered'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        mock_award.assert_not_called()

    @patch('orders.views.award_points')
    def test_delivering_paid_guest_order_logs_and_skips_award(self, mock_award):
        order = Order.objects.create(
            tenant=self.tenant, order_type='takeaway', guest_name='Walk-in',
            status='confirmed', total_price=Decimal('15.00'),
        )
        with self.assertLogs('orders.views', level='INFO') as cm:
            resp = self.client.patch(f'/api/orders/{order.id}/admin-update/', {'status': 'delivered'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        mock_award.assert_not_called()
        self.assertTrue(any('award_points skipped' in msg for msg in cm.output))


class AdminUpdateOrderCancelRestockTests(TestCase):
    """Covers the cancel/restock branches (product-deleted continue + activity log)."""

    def setUp(self):
        self.tenant = make_tenant(slug='restockdiner')
        self.owner = make_user('owner@restockdiner.com', self.tenant, role='owner')
        self.category = ProductCategory.objects.create(tenant=self.tenant, name='Snacks', slug='snacks')
        self.product = Product.objects.create(
            tenant=self.tenant, category=self.category, name='Chips', price=Decimal('2.00'), stock=10,
        )
        self.client = APIClient()
        self.client.defaults['HTTP_HOST'] = 'restockdiner.bizal.al'
        self.client.force_authenticate(user=self.owner)

    def test_cancelling_order_restocks_product_and_logs_activity(self):
        order = Order.objects.create(tenant=self.tenant, order_type='takeaway', guest_name='G', status='pending')
        OrderItem.objects.create(order=order, product=self.product, quantity=3, unit_price=Decimal('2.00'))
        resp = self.client.patch(f'/api/orders/{order.id}/admin-update/', {'status': 'cancelled'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 13)
        from activity.models import ActivityLog
        self.assertTrue(
            ActivityLog.objects.filter(tenant=self.tenant, verb='inventory.stock_adjusted').exists()
        )

    def test_cancelling_order_with_deleted_product_skips_restock_gracefully(self):
        # on_delete=PROTECT means a real Product can never actually be deleted
        # while an OrderItem still references it, so the "product was deleted
        # since" case this guards against can only be exercised by mocking
        # the locked-products lookup to come back empty, as if the id no
        # longer resolves to any row.
        order = Order.objects.create(tenant=self.tenant, order_type='takeaway', guest_name='G', status='pending')
        OrderItem.objects.create(order=order, product=self.product, quantity=2, unit_price=Decimal('2.00'))
        with patch('orders.views.Product.objects.select_for_update') as mock_sfu:
            mock_sfu.return_value.filter.return_value = Product.objects.none()
            resp = self.client.patch(f'/api/orders/{order.id}/admin-update/', {'status': 'cancelled'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 10)  # unchanged: locked dict was empty, restock skipped

    @patch('activity.utils.log_activity', side_effect=Exception('logging backend down'))
    def test_activity_log_failure_never_blocks_cancellation(self, mock_log):
        order = Order.objects.create(tenant=self.tenant, order_type='takeaway', guest_name='G', status='pending')
        OrderItem.objects.create(order=order, product=self.product, quantity=1, unit_price=Decimal('2.00'))
        resp = self.client.patch(f'/api/orders/{order.id}/admin-update/', {'status': 'cancelled'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 11)


def make_tenant__models_gaps(slug='itemname-gap'):
    return Tenant.objects.create(
        name='Item Name Co', slug=slug, business_type='restaurant',
        plan='pro', is_active=True,
    )


class OrderItemItemNameGapsTests(TestCase):
    def setUp(self):
        self.tenant = make_tenant__models_gaps()
        self.order = Order.objects.create(tenant=self.tenant, order_type='dine_in')

    def test_item_name_from_menu_item(self):
        category = MenuCategory.objects.create(tenant=self.tenant, name='Mains')
        menu_item = MenuItem.objects.create(
            tenant=self.tenant, category=category, name='Burger', price=Decimal('9.50'),
        )
        line = OrderItem.objects.create(order=self.order, menu_item=menu_item, quantity=1, unit_price=menu_item.price)
        self.assertEqual(line.item_name, 'Burger')

    def test_item_name_from_product(self):
        product = Product.objects.create(tenant=self.tenant, name='Widget', price=Decimal('5.00'))
        line = OrderItem.objects.create(order=self.order, product=product, quantity=1, unit_price=product.price)
        self.assertEqual(line.item_name, 'Widget')

    def test_item_name_empty_when_neither_set(self):
        # In-memory only (not saved) — saving would violate the
        # "exactly one of menu_item/product" CheckConstraint.
        line = OrderItem(order=self.order, quantity=1, unit_price=Decimal('1.00'))
        self.assertEqual(line.item_name, '')


def make_tenant__serializers_gaps(slug='diner', **kwargs):
    defaults = dict(name='Test Diner', slug=slug, business_type='shop', plan='pro', is_active=True)
    defaults.update(kwargs)
    return Tenant.objects.create(**defaults)


class TenantFieldNoTenantTest(TestCase):
    """Covers the `if tenant:` else-branch (no request.tenant in context)."""

    def test_menu_item_field_no_tenant(self):
        field = TenantMenuItemField(required=False)
        field._context = {'request': None}
        self.assertEqual(field.get_queryset().count(), 0)

    def test_product_field_no_tenant(self):
        field = TenantProductField(required=False)
        field._context = {'request': None}
        self.assertEqual(field.get_queryset().count(), 0)


class OrderItemValidateTest(TestCase):
    def setUp(self):
        self.tenant = make_tenant__serializers_gaps(slug='validatebiz')
        self.category = MenuCategory.objects.create(tenant=self.tenant, name='Mains')
        self.item = MenuItem.objects.create(tenant=self.tenant, category=self.category, name='Burger', price=Decimal('9.50'))
        self.pcategory = ProductCategory.objects.create(tenant=self.tenant, name='Cat', slug='cat')
        self.product = Product.objects.create(tenant=self.tenant, category=self.pcategory, name='Widget', price=5, stock=10)

    def test_neither_menu_item_nor_product_rejected(self):
        with self.assertRaises(Exception):
            OrderItemSerializer().validate({'quantity': 1})

    def test_both_menu_item_and_product_rejected(self):
        with self.assertRaises(Exception):
            OrderItemSerializer().validate({'menu_item': self.item, 'product': self.product, 'quantity': 1})


class OrderCreateGapsTest(TestCase):
    def setUp(self):
        self.tenant = make_tenant__serializers_gaps(slug='ordergaps')
        self.category = MenuCategory.objects.create(tenant=self.tenant, name='Mains')
        self.item = MenuItem.objects.create(
            tenant=self.tenant, category=self.category, name='Burger', price=Decimal('9.50'), is_available=False,
        )
        self.pcategory = ProductCategory.objects.create(tenant=self.tenant, name='Cat', slug='cat')
        self.product = Product.objects.create(
            tenant=self.tenant, category=self.pcategory, name='Widget', price=5, stock=10, is_active=False,
        )
        self.active_product = Product.objects.create(
            tenant=self.tenant, category=self.pcategory, name='Gadget', price=5, stock=1, is_active=True,
        )
        self.client = APIClient()
        self.client.defaults['HTTP_HOST'] = 'ordergaps.bizal.al'

    def test_unavailable_menu_item_rejected(self):
        resp = self.client.post('/api/orders/', {
            'guest_name': 'Walk-in', 'guest_phone': '0691234567', 'order_type': 'dine_in',
            'items': [{'menu_item': str(self.item.id), 'quantity': 1}],
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('items', resp.data)

    def test_inactive_product_rejected(self):
        resp = self.client.post('/api/orders/', {
            'guest_name': 'Walk-in', 'guest_phone': '0691234567', 'order_type': 'delivery',
            'items': [{'product': str(self.product.id), 'quantity': 1}],
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('items', resp.data)

    def test_race_condition_insufficient_stock_under_lock(self):
        """
        Pre-check passes (stock=1 >= needed=1), but a mocked select_for_update
        snapshot simulates a concurrent order depleting stock between the
        pre-check and the lock, exercising the still_insufficient branch.
        """
        from orders import serializers as ser_module

        depleted = Product.objects.get(pk=self.active_product.pk)
        depleted.stock = 0

        class FakeQS:
            def filter(self, **kwargs):
                return [depleted]

        with patch.object(ser_module.Product.objects, 'select_for_update', return_value=FakeQS()):
            resp = self.client.post('/api/orders/', {
                'guest_name': 'Walk-in', 'guest_phone': '0691234567', 'order_type': 'delivery',
                'items': [{'product': str(self.active_product.id), 'quantity': 1}],
            }, format='json')
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertIn('items', resp.data)

    def test_activity_log_exception_does_not_block_order(self):
        with patch('activity.utils.log_activity', side_effect=Exception('boom')):
            resp = self.client.post('/api/orders/', {
                'guest_name': 'Walk-in', 'guest_phone': '0691234567', 'order_type': 'delivery',
                'items': [{'product': str(self.active_product.id), 'quantity': 1}],
            }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)


class OrderPaymentMethodTests(TestCase):
    def setUp(self):
        self.tenant = make_tenant(slug='paymethoddiner')
        self.category = MenuCategory.objects.create(tenant=self.tenant, name='Mains')
        self.item = MenuItem.objects.create(
            tenant=self.tenant, category=self.category, name='Pasta', price=Decimal('10.00'),
        )
        self.client = APIClient()
        self.client.defaults['HTTP_HOST'] = 'paymethoddiner.bizal.al'

    def test_payment_method_defaults_to_cash(self):
        resp = self.client.post('/api/orders/', {
            'guest_name': 'Walk-in', 'order_type': 'dine_in',
            'items': [{'menu_item': str(self.item.id), 'quantity': 1}],
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data['payment_method'], 'cash')

    def test_customer_can_choose_bank_transfer(self):
        resp = self.client.post('/api/orders/', {
            'guest_name': 'Walk-in', 'order_type': 'takeaway',
            'payment_method': 'bank_transfer',
            'items': [{'menu_item': str(self.item.id), 'quantity': 1}],
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data['payment_method'], 'bank_transfer')

    def test_invalid_payment_method_rejected(self):
        resp = self.client.post('/api/orders/', {
            'guest_name': 'Walk-in', 'order_type': 'takeaway',
            'payment_method': 'online',
            'items': [{'menu_item': str(self.item.id), 'quantity': 1}],
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('payment_method', resp.data)