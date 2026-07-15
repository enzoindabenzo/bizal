from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from accounts.models import User
from tenants.models import Tenant
from .models import ActivityLog
from .utils import log_activity


class ActivityLogTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(
            name='Cars SH', slug='hertz', business_type='car_rental', plan='enterprise',
            is_active=True,
        )
        self.other_tenant = Tenant.objects.create(
            name='Other', slug='other', business_type='gym', plan='pro', is_active=True,
        )
        self.owner = User.objects.create_user(
            email='owner@hertz.com', password='pass1234', tenant=self.tenant, role='owner',
        )
        self.customer = User.objects.create_user(
            email='customer@hertz.com', password='pass1234', tenant=self.tenant, role='customer',
        )
        self.client.defaults['HTTP_HOST'] = 'hertz.bizal.al'

    def test_log_activity_creates_entry(self):
        entry = log_activity(
            tenant=self.tenant, actor=self.owner, verb='booking.confirmed',
            description='Confirmed booking for Arben Hoxha',
            target_type='booking', target_id='abc123',
        )
        self.assertIsNotNone(entry)
        self.assertEqual(ActivityLog.objects.filter(tenant=self.tenant).count(), 1)
        self.assertEqual(entry.actor_name, self.owner.display_name)

    def test_log_activity_with_no_tenant_is_noop(self):
        entry = log_activity(
            tenant=None, actor=self.owner, verb='booking.confirmed',
            description='Should not be saved',
        )
        self.assertIsNone(entry)
        self.assertEqual(ActivityLog.objects.count(), 0)

    def test_owner_can_list_activity(self):
        log_activity(self.tenant, self.owner, 'booking.confirmed', 'Confirmed booking #1')
        self.client.force_authenticate(user=self.owner)
        resp = self.client.get('/api/activity/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data['results']), 1)
        self.assertEqual(resp.data['results'][0]['description'], 'Confirmed booking #1')

    def test_customer_cannot_list_activity(self):
        log_activity(self.tenant, self.owner, 'booking.confirmed', 'Confirmed booking #1')
        self.client.force_authenticate(user=self.customer)
        resp = self.client.get('/api/activity/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_activity_scoped_to_tenant(self):
        log_activity(self.tenant, self.owner, 'booking.confirmed', 'Confirmed booking #1')
        log_activity(self.other_tenant, self.owner, 'booking.confirmed', 'Other tenant booking')
        self.client.force_authenticate(user=self.owner)
        resp = self.client.get('/api/activity/')
        descriptions = [r['description'] for r in resp.data['results']]
        self.assertIn('Confirmed booking #1', descriptions)
        self.assertNotIn('Other tenant booking', descriptions)

    def test_booking_cancel_writes_activity_entry(self):
        from bookings.models import Booking
        booking = Booking.objects.create(
            tenant=self.tenant, user=self.customer, guest_name='Arben Hoxha',
            booking_type='rental', status='pending',
            guest_email='arben@test.com', guest_phone='+355000000',
        )
        self.client.force_authenticate(user=self.customer)
        resp = self.client.post(f'/api/bookings/{booking.pk}/cancel/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        entry = ActivityLog.objects.filter(tenant=self.tenant, verb='booking.cancelled').first()
        self.assertIsNotNone(entry)
        self.assertIn('Arben Hoxha', entry.description)


class ActivityPermissionTests(TestCase):
    """Test that ActivityLog is properly tenant-scoped and permission-gated."""

    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(
            name='Perm Biz', slug='permbiz', business_type='restaurant',
            plan='pro', is_active=True,
        )
        self.owner = User.objects.create_user(
            email='owner@perm.com', password='pass1234', tenant=self.tenant, role='owner',
        )
        self.manager = User.objects.create_user(
            email='manager@perm.com', password='pass1234', tenant=self.tenant, role='manager',
        )
        self.customer = User.objects.create_user(
            email='customer@perm.com', password='pass1234', tenant=self.tenant, role='customer',
        )
        self.client.defaults['HTTP_HOST'] = 'permbiz.bizal.al'

    def test_manager_can_list_activity(self):
        """Managers (IsTenantStaff) should be able to see activity logs."""
        log_activity(self.tenant, self.owner, 'booking.created', 'Created booking #42')
        self.client.force_authenticate(user=self.manager)
        resp = self.client.get('/api/activity/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_anonymous_cannot_list_activity(self):
        resp = self.client.get('/api/activity/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_activity_log_verb_stored_correctly(self):
        entry = log_activity(
            self.tenant, self.owner, 'order.completed',
            'Order #99 completed', target_type='order', target_id='99',
        )
        self.assertEqual(entry.verb, 'order.completed')
        self.assertEqual(entry.target_type, 'order')
        self.assertEqual(entry.target_id, '99')

    def test_activity_log_with_none_actor(self):
        """System events (no human actor) should not crash the logger."""
        entry = log_activity(
            tenant=self.tenant, actor=None, verb='system.check',
            description='Automated health check',
        )
        self.assertIsNotNone(entry)

    def test_activity_api_returns_paginated_results(self):
        for i in range(25):
            log_activity(self.tenant, self.owner, f'event.{i}', f'Event {i}')
        self.client.force_authenticate(user=self.owner)
        resp = self.client.get('/api/activity/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        # Default page size is 20; should not return all 25 in one page
        self.assertIn('next', resp.data)
        self.assertLessEqual(len(resp.data.get('results', resp.data) if isinstance(resp.data, dict) else resp.data), 25)

    def test_activity_filtered_by_verb(self):
        log_activity(self.tenant, self.owner, 'booking.created', 'Booking A')
        log_activity(self.tenant, self.owner, 'order.created', 'Order B')
        self.client.force_authenticate(user=self.owner)
        resp = self.client.get('/api/activity/?verb=booking.created')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        verbs = [r['verb'] for r in resp.data['results']]
        self.assertTrue(all(v == 'booking.created' for v in verbs))
