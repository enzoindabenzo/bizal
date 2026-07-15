from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from accounts.models import User
from tenants.models import Tenant


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
        self.client.defaults['HTTP_HOST'] = 'entco.bizal.al'
        self.client.force_authenticate(user=self.owner)
        resp = self.client.get('/api/analytics/?export=csv')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp['Content-Type'], 'text/csv')

    # ── H-2: dedicated export endpoints must respect csv_export plan gate ──

    def test_export_bookings_csv_blocked_for_pro(self):
        """
        H-2 regression test: /api/analytics/export/bookings/ previously
        had no feature check at all, unlike the inline export on
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


# ── AnalyticsEvent model + track() util ───────────────────────────────────────

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
        H-3 regression test: TrackEventView (the public, AllowAny,
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
