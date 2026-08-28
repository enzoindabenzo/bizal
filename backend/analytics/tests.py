from django.test import TestCase

from rest_framework.test import APIClient

from rest_framework import status

from accounts.models import User

from tenants.models import Tenant

from unittest.mock import patch

from tenants.models import Tenant, PLAN_TRIAL

from .models import AnalyticsEvent

from datetime import timedelta

from django.utils import timezone

from .tasks import purge_old_events

from rest_framework.test import APIRequestFactory

from analytics.models import AnalyticsEvent

from analytics.utils import track


class AnalyticsTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(
            name='Enterprise Co', slug='entco', business_type='hotel', plan='enterprise',
            is_active=True,
        )
        self.owner = User.objects.create_user(
            email='owner@entco.com', password='pass1234', tenant=self.tenant, role='owner',
        )
        self.pro_tenant = Tenant.objects.create(
            name='Pro Co', slug='proco', business_type='restaurant', plan='pro',
            is_active=True,
        )
        self.pro_owner = User.objects.create_user(
            email='owner@proco.com', password='pass1234', tenant=self.pro_tenant, role='owner',
        )

    def test_analytics_available_for_enterprise(self):
        self.client.defaults['HTTP_HOST'] = 'entco.bizal.al'
        self.client.force_authenticate(user=self.owner)
        resp = self.client.get('/api/analytics/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('bookings', resp.data)
        self.assertIn('reviews', resp.data)
        self.assertIn('contacts', resp.data)
        self.assertIn('leads', resp.data)
        self.assertIn('new_customers', resp.data)

    def test_analytics_available_for_pro(self):
        # The Pro plan now includes analytics (PLAN_FEATURES['pro']['analytics'] = True).
        self.client.defaults['HTTP_HOST'] = 'proco.bizal.al'
        self.client.force_authenticate(user=self.pro_owner)
        resp = self.client.get('/api/analytics/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_analytics_blocked_for_starter(self):
        starter_tenant = Tenant.objects.create(
            name='Starter Co', slug='starterco', business_type='restaurant', plan='starter',
            is_active=True,
        )
        starter_owner = User.objects.create_user(
            email='owner@starterco.com', password='pass1234', tenant=starter_tenant, role='owner',
        )
        self.client.defaults['HTTP_HOST'] = 'starterco.bizal.al'
        self.client.force_authenticate(user=starter_owner)
        resp = self.client.get('/api/analytics/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_analytics_requires_auth(self):
        self.client.defaults['HTTP_HOST'] = 'entco.bizal.al'
        resp = self.client.get('/api/analytics/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_csv_export_enterprise(self):
        from bookings.models import Booking
        Booking.objects.create(
            tenant=self.tenant, booking_type='room', status='completed',
            guest_name='Row Guest', total_price=50,
        )
        self.client.defaults['HTTP_HOST'] = 'entco.bizal.al'
        self.client.force_authenticate(user=self.owner)
        resp = self.client.get('/api/analytics/?export=csv')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp['Content-Type'], 'text/csv')
        content = resp.content.decode('utf-8')
        self.assertIn('Month,Bookings', content)

    # ── Dedicated export endpoints must respect csv_export plan gate ──

    def test_export_bookings_csv_blocked_for_pro(self):
        """
        /api/analytics/export/bookings/ must respect the same feature
        check as the inline export on
        analytics_dashboard (?export=csv). A Pro-plan owner (csv_export
        False, see PLAN_FEATURES) must be blocked here too.
        """
        self.client.defaults['HTTP_HOST'] = 'proco.bizal.al'
        self.client.force_authenticate(user=self.pro_owner)
        resp = self.client.get('/api/analytics/export/bookings/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_export_orders_csv_blocked_for_pro(self):
        self.client.defaults['HTTP_HOST'] = 'proco.bizal.al'
        self.client.force_authenticate(user=self.pro_owner)
        resp = self.client.get('/api/analytics/export/orders/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_export_customers_csv_blocked_for_pro(self):
        self.client.defaults['HTTP_HOST'] = 'proco.bizal.al'
        self.client.force_authenticate(user=self.pro_owner)
        resp = self.client.get('/api/analytics/export/customers/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_export_bookings_csv_allowed_for_enterprise(self):
        self.client.defaults['HTTP_HOST'] = 'entco.bizal.al'
        self.client.force_authenticate(user=self.owner)
        resp = self.client.get('/api/analytics/export/bookings/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp['Content-Type'], 'text/csv; charset=utf-8')

    def test_export_orders_csv_allowed_for_enterprise(self):
        self.client.defaults['HTTP_HOST'] = 'entco.bizal.al'
        self.client.force_authenticate(user=self.owner)
        resp = self.client.get('/api/analytics/export/orders/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_export_customers_csv_allowed_for_enterprise(self):
        self.client.defaults['HTTP_HOST'] = 'entco.bizal.al'
        self.client.force_authenticate(user=self.owner)
        resp = self.client.get('/api/analytics/export/customers/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_inline_csv_export_blocked_when_analytics_allowed_but_no_csv_export(self):
        """Companion check: pro plan has analytics=True but csv_export=False —
        the inline ?export=csv branch on analytics_dashboard must still 403
        rather than silently falling through to the JSON response."""
        self.client.defaults['HTTP_HOST'] = 'proco.bizal.al'
        self.client.force_authenticate(user=self.pro_owner)
        resp = self.client.get('/api/analytics/?export=csv')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_invalid_start_date_format_returns_400(self):
        self.client.defaults['HTTP_HOST'] = 'entco.bizal.al'
        self.client.force_authenticate(user=self.owner)
        resp = self.client.get('/api/analytics/?start_date=not-a-date')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_end_date_format_returns_400(self):
        self.client.defaults['HTTP_HOST'] = 'entco.bizal.al'
        self.client.force_authenticate(user=self.owner)
        resp = self.client.get('/api/analytics/?end_date=31-12-2026')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_date_filters_apply_across_all_querysets(self):
        """Exercises the start_date/end_date branches on bookings, reviews,
        contacts, leads, customers, appointments, and orders querysets."""
        self.client.defaults['HTTP_HOST'] = 'entco.bizal.al'
        self.client.force_authenticate(user=self.owner)
        resp = self.client.get('/api/analytics/?start_date=2020-01-01&end_date=2030-01-01')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('orders', resp.data)

    def test_orders_fetch_exception_falls_back_gracefully(self):
        """If loading Order data raises, analytics_dashboard must still
        return 200 with orders zeroed out rather than 500ing."""
        from unittest.mock import patch
        self.client.defaults['HTTP_HOST'] = 'entco.bizal.al'
        self.client.force_authenticate(user=self.owner)
        with patch('orders.models.Order.objects.filter', side_effect=RuntimeError('db exploded')):
            resp = self.client.get('/api/analytics/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['orders']['count'], 0)
        self.assertEqual(resp.data['orders']['revenue'], 0)

    def test_track_event_without_tenant_returns_400(self):
        self.client.defaults['HTTP_HOST'] = 'bizal.al'
        resp = self.client.post('/api/analytics/track/', {'event_type': 'page_view'})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_export_bookings_csv_row_content_and_formula_injection_escape(self):
        from bookings.models import Booking
        Booking.objects.create(
            tenant=self.tenant, booking_type='room', status='completed',
            guest_name='=SUM(A1)', guest_email='a@a.com', guest_phone='123',
            total_price=10,
        )
        self.client.defaults['HTTP_HOST'] = 'entco.bizal.al'
        self.client.force_authenticate(user=self.owner)
        resp = self.client.get('/api/analytics/export/bookings/')
        content = resp.content.decode('utf-8-sig')
        self.assertIn("'=SUM(A1)", content)

    def test_export_orders_csv_row_content(self):
        from menu.models import MenuCategory, MenuItem
        from orders.models import Order, OrderItem
        cat = MenuCategory.objects.create(tenant=self.tenant, name='Main')
        item = MenuItem.objects.create(tenant=self.tenant, category=cat, name='Pizza', price=8)
        order = Order.objects.create(tenant=self.tenant, order_type='dine_in', guest_name='Test G', guest_phone='555')
        OrderItem.objects.create(order=order, menu_item=item, quantity=2, unit_price=item.price)
        self.client.defaults['HTTP_HOST'] = 'entco.bizal.al'
        self.client.force_authenticate(user=self.owner)
        resp = self.client.get('/api/analytics/export/orders/')
        content = resp.content.decode('utf-8-sig')
        self.assertIn('Pizza x2', content)

    def test_export_customers_csv_row_content(self):
        User.objects.create_user(
            email='cust@entco.com', password='pass1234', tenant=self.tenant,
            role='customer', full_name='Customer Name',
        )
        self.client.defaults['HTTP_HOST'] = 'entco.bizal.al'
        self.client.force_authenticate(user=self.owner)
        resp = self.client.get('/api/analytics/export/customers/')
        content = resp.content.decode('utf-8-sig')
        self.assertIn('cust@entco.com', content)


class AnalyticsEventSerializerTest(TestCase):
    def test_serializes_expected_fields(self):
        from tenants.models import Tenant
        from analytics.models import AnalyticsEvent
        from analytics.serializers import AnalyticsEventSerializer
        tenant = Tenant.objects.create(
            name='SerCo', slug='serco', business_type='restaurant', plan='pro', is_active=True,
        )
        event = AnalyticsEvent.objects.create(tenant=tenant, event_type='page_view', page='/home')
        data = AnalyticsEventSerializer(event).data
        self.assertEqual(data['event_type'], 'page_view')
        self.assertEqual(data['page'], '/home')
        self.assertIn('id', data)
        self.assertIn('created_at', data)


class AnalyticsEventModelTest(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            name='Track Co', slug='trackco', business_type='restaurant',
            plan='enterprise', is_active=True,
        )

    def test_track_creates_event(self):
        from analytics.utils import track
        from rest_framework.test import APIRequestFactory
        factory = APIRequestFactory()
        request = factory.get('/', SERVER_NAME='trackco.bizal.al')
        request.META['REMOTE_ADDR'] = '127.0.0.1'
        track(request, self.tenant, 'page_view', page='/services/')
        from analytics.models import AnalyticsEvent
        self.assertEqual(AnalyticsEvent.objects.filter(tenant=self.tenant).count(), 1)
        ev = AnalyticsEvent.objects.get(tenant=self.tenant)
        self.assertEqual(ev.event_type, 'page_view')
        self.assertEqual(ev.page, '/services/')

    def test_track_hashes_ip(self):
        from analytics.utils import track
        from analytics.models import AnalyticsEvent
        from rest_framework.test import APIRequestFactory
        factory = APIRequestFactory()
        request = factory.get('/')
        request.META['REMOTE_ADDR'] = '192.168.1.1'
        track(request, self.tenant, 'whatsapp_click')
        ev = AnalyticsEvent.objects.get(tenant=self.tenant)
        self.assertNotEqual(ev.ip_hash, '192.168.1.1')   # must be hashed
        self.assertTrue(len(ev.ip_hash) > 0)

    def test_track_event_api_endpoint(self):
        from rest_framework.test import APIClient
        client = APIClient()
        client.defaults['HTTP_HOST'] = 'trackco.bizal.al'
        resp = client.post('/api/analytics/track/', {
            'event_type': 'page_view', 'page': '/menu/',
        })
        self.assertEqual(resp.status_code, 200)
        from analytics.models import AnalyticsEvent
        self.assertEqual(AnalyticsEvent.objects.filter(tenant=self.tenant).count(), 1)

    def test_track_silently_ignores_invalid_event_type(self):
        """track() should never raise even if data is bad."""
        from analytics.utils import track
        from rest_framework.test import APIRequestFactory
        factory = APIRequestFactory()
        request = factory.get('/')
        # Should not raise
        track(request, self.tenant, 'unknown_event_xyz')

    def test_track_event_api_rejects_invalid_event_type(self):
        """
        Regression test: TrackEventView (the public, AllowAny,
        rate-limited-only-by-IP endpoint) must reject an event_type that
        isn't in AnalyticsEvent's real choice set, instead of writing it
        straight to the DB via track(). This is distinct from
        test_track_silently_ignores_invalid_event_type above, which
        exercises the lower-level track() helper directly (used
        internally by other apps that already pass a known-good
        event_type) and is intentionally permissive — TrackEventView is
        the untrusted, public-facing entry point and must validate.
        """
        from rest_framework.test import APIClient
        client = APIClient()
        client.defaults['HTTP_HOST'] = 'trackco.bizal.al'
        resp = client.post('/api/analytics/track/', {
            'event_type': 'totally_made_up_event', 'page': '/menu/',
        })
        self.assertEqual(resp.status_code, 400)
        from analytics.models import AnalyticsEvent
        self.assertEqual(AnalyticsEvent.objects.filter(tenant=self.tenant).count(), 0)


class AnalyticsDashboardNoTenantGuardTest(TestCase):
    """
    analytics_dashboard()'s `if not tenant` guard is defensively
    unreachable via HTTP (IsTenantOwner.has_permission already blocks
    no-tenant requests), so we hit it with the permission check patched
    to allow the request through, on the main domain (request.tenant
    is None there).
    """

    def test_no_tenant_returns_400(self):
        client = APIClient()
        superuser = User.objects.create_superuser(email='root@bizal.al', password='pass1234')
        client.force_authenticate(user=superuser)
        with patch('tenants.permissions.IsTenantOwner.has_permission', return_value=True):
            resp = client.get('/api/analytics/')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data['detail'], 'No tenant.')


class AnalyticsEventStrTests(TestCase):
    def test_str_includes_tenant_slug_and_event_type(self):
        tenant = Tenant.objects.create(
            name='Str Co', slug='analytics-str-co', business_type='restaurant',
            is_active=True, plan=PLAN_TRIAL,
        )
        event = AnalyticsEvent.objects.create(tenant=tenant, event_type='page_view', page='/x')
        text = str(event)
        self.assertIn('analytics-str-co', text)
        self.assertIn('page_view', text)


def make_tenant(**kwargs):
    defaults = dict(
        name='Analytics Test Biz', slug='analytics-test-biz', business_type='restaurant',
        is_active=True, plan=PLAN_TRIAL,
    )
    defaults.update(kwargs)
    return Tenant.objects.create(**defaults)


def make_event(tenant, days_old, **kwargs):
    defaults = dict(tenant=tenant, event_type='page_view', page='/x')
    defaults.update(kwargs)
    ev = AnalyticsEvent.objects.create(**defaults)
    # created_at is auto_now_add — bypass via a queryset .update() (raw SQL,
    # doesn't re-trigger auto_now_add) to backdate it for the purge window.
    AnalyticsEvent.objects.filter(pk=ev.pk).update(
        created_at=timezone.now() - timedelta(days=days_old)
    )
    return ev


def deactivate_all_tenants():
    # A seeded "main" sentinel tenant (migration 0019_main_sentinel_tenant)
    # is always present and active — must be deactivated too, or the
    # "no active tenants" fallback branch never actually triggers.
    Tenant.objects.update(is_active=False)


class PurgeOldEventsPerTenantTests(TestCase):
    def setUp(self):
        self.tenant = make_tenant()

    @patch('time.sleep', return_value=None)
    def test_purges_old_events_for_active_tenant(self, mock_sleep):
        old = make_event(self.tenant, days_old=100)
        recent = make_event(self.tenant, days_old=1)
        result = purge_old_events(days=90, batch_size=10)
        self.assertFalse(AnalyticsEvent.objects.filter(pk=old.pk).exists())
        self.assertTrue(AnalyticsEvent.objects.filter(pk=recent.pk).exists())
        self.assertIn('Purged 1', result)

    @patch('time.sleep', return_value=None)
    def test_no_old_events_for_tenant_purges_nothing(self, mock_sleep):
        make_event(self.tenant, days_old=1)
        result = purge_old_events(days=90, batch_size=10)
        self.assertIn('Purged 0', result)
        self.assertEqual(AnalyticsEvent.objects.count(), 1)

    @patch('time.sleep', return_value=None)
    def test_multiple_active_tenants_each_get_purged(self, mock_sleep):
        tenant2 = make_tenant(slug='analytics-test-biz-2')
        old1 = make_event(self.tenant, days_old=100)
        old2 = make_event(tenant2, days_old=100)
        result = purge_old_events(days=90, batch_size=10)
        self.assertFalse(AnalyticsEvent.objects.filter(pk=old1.pk).exists())
        self.assertFalse(AnalyticsEvent.objects.filter(pk=old2.pk).exists())
        self.assertIn('Purged 2', result)

    @patch('time.sleep', return_value=None)
    def test_full_batch_continues_to_next_batch(self, mock_sleep):
        # batch_size=2 with 3 old rows forces a full batch (deleted == batch_size),
        # exercising the time.sleep() branch and a second iteration of the loop.
        for _ in range(3):
            make_event(self.tenant, days_old=100)
        result = purge_old_events(days=90, batch_size=2)
        self.assertIn('Purged 3', result)
        mock_sleep.assert_called()

    @patch('time.sleep', return_value=None)
    def test_inactive_tenant_is_skipped(self, mock_sleep):
        inactive = make_tenant(slug='analytics-inactive', is_active=False)
        old = make_event(inactive, days_old=100)
        purge_old_events(days=90, batch_size=10)
        # Inactive tenant's id never enters tenant_ids, so its old rows survive.
        self.assertTrue(AnalyticsEvent.objects.filter(pk=old.pk).exists())


class PurgeOldEventsFallbackTests(TestCase):
    @patch('time.sleep', return_value=None)
    def test_import_failure_falls_back_to_global_ordering(self, mock_sleep):
        tenant = make_tenant()
        old = make_event(tenant, days_old=100)
        recent = make_event(tenant, days_old=1)
        with patch('tenants.models.Tenant.objects.filter', side_effect=Exception('boom')):
            result = purge_old_events(days=90, batch_size=10)
        self.assertFalse(AnalyticsEvent.objects.filter(pk=old.pk).exists())
        self.assertTrue(AnalyticsEvent.objects.filter(pk=recent.pk).exists())
        self.assertIn('Purged 1', result)

    @patch('time.sleep', return_value=None)
    def test_no_active_tenants_falls_back_and_finds_nothing(self, mock_sleep):
        deactivate_all_tenants()
        result = purge_old_events(days=90, batch_size=10)
        self.assertIn('Purged 0', result)

    @patch('time.sleep', return_value=None)
    def test_fallback_full_batch_continues_to_next_iteration(self, mock_sleep):
        # No active tenants -> fallback (global-ordering) loop. batch_size=2
        # with 3 old rows forces a full batch (deleted == batch_size) on the
        # first pass, exercising the fallback loop's time.sleep() branch and
        # a second iteration, rather than breaking out after a partial batch.
        deactivate_all_tenants()
        tenant = make_tenant(slug='analytics-fallback-full', is_active=False)
        for _ in range(3):
            make_event(tenant, days_old=100)
        result = purge_old_events(days=90, batch_size=2)
        self.assertIn('Purged 3', result)
        mock_sleep.assert_called()


class TrackGapsTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()

    def test_none_tenant_is_a_noop(self):
        request = self.factory.get('/')
        track(request, None, 'page_view')
        self.assertEqual(AnalyticsEvent.objects.count(), 0)

    def test_tenant_without_analytics_feature_is_a_noop(self):
        tenant = Tenant.objects.create(
            name='Starter Co', slug='starterco-track', business_type='restaurant',
            plan='starter', is_active=True,
        )
        self.assertFalse(tenant.has_feature('analytics'))
        request = self.factory.get('/')
        track(request, tenant, 'page_view')
        self.assertEqual(AnalyticsEvent.objects.filter(tenant=tenant).count(), 0)

    def test_exception_during_create_is_silenced(self):
        tenant = Tenant.objects.create(
            name='Ent Co', slug='entco-track', business_type='restaurant',
            plan='enterprise', is_active=True,
        )
        request = self.factory.get('/')
        with patch('analytics.utils.AnalyticsEvent.objects.create', side_effect=Exception('db down')):
            try:
                track(request, tenant, 'page_view')
            except Exception as exc:
                self.fail(f'track() raised unexpectedly: {exc}')
