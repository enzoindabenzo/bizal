from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from accounts.models import User
from tenants.models import Tenant
from .models import Notification
from .utils import notify_owner, notify_user


def make_tenant(slug, plan='pro'):
    return Tenant.objects.create(
        name=slug.title(), slug=slug, plan=plan,
        is_active=True, business_type='restaurant',
    )


def make_user(email, tenant, role='customer'):
    return User.objects.create_user(
        email=email, password='pass1234', tenant=tenant, role=role,
    )


# ── Model / util tests ────────────────────────────────────────────────────────

class NotificationUtilsTest(TestCase):
    def setUp(self):
        self.tenant = make_tenant('notifbiz')
        self.owner = make_user('owner@notifbiz.com', self.tenant, 'owner')
        self.manager = make_user('mgr@notifbiz.com', self.tenant, 'manager')
        self.customer = make_user('cust@notifbiz.com', self.tenant, 'customer')

    def test_notify_owner_creates_for_all_owners_and_managers(self):
        notify_owner(self.tenant, 'info', 'Hello', 'Body text')
        count = Notification.objects.filter(tenant=self.tenant).count()
        # Should have created one for owner + one for manager
        self.assertEqual(count, 2)

    def test_notify_owner_does_not_notify_customers(self):
        notify_owner(self.tenant, 'info', 'Owners only', 'Body')
        notified_users = Notification.objects.filter(
            tenant=self.tenant
        ).values_list('user_id', flat=True)
        self.assertIn(self.owner.id, notified_users)
        self.assertIn(self.manager.id, notified_users)
        self.assertNotIn(self.customer.id, notified_users)

    def test_notify_user_creates_single_notification(self):
        notify_user(self.customer, self.tenant, 'info', 'Hi', 'Welcome!')
        n = Notification.objects.get(user=self.customer, tenant=self.tenant)
        self.assertEqual(n.title, 'Hi')
        self.assertEqual(n.body, 'Welcome!')
        self.assertFalse(n.is_read)

    def test_notify_user_inactive_user_skipped(self):
        self.customer.is_active = False
        self.customer.save()
        notify_user(self.customer, self.tenant, 'info', 'Skipped', 'Should not appear')
        self.assertEqual(
            Notification.objects.filter(user=self.customer).count(), 0
        )

    def test_notify_owner_with_metadata(self):
        notify_owner(
            self.tenant, 'booking_confirmed', 'New Booking', 'Arben booked.',
            metadata={'booking_id': 'abc-123'},
        )
        n = Notification.objects.get(user=self.owner)
        self.assertEqual(n.metadata['booking_id'], 'abc-123')

    def test_notification_str(self):
        n = Notification.objects.create(
            tenant=self.tenant, user=self.owner,
            notification_type='info', title='T', body='B',
        )
        self.assertIn(str(self.owner), str(n))

    def test_bulk_create_efficiency(self):
        """notify_owner uses bulk_create — should result in exactly 2 DB rows."""
        from django.test.utils import CaptureQueriesContext
        from django.db import connection
        with CaptureQueriesContext(connection) as ctx:
            notify_owner(self.tenant, 'info', 'Bulk', 'Test')
        # Should use a single INSERT (bulk_create) plus a SELECT for owners list
        insert_queries = [q for q in ctx.captured_queries if 'INSERT' in q['sql'].upper()]
        self.assertEqual(len(insert_queries), 1)

    # ── M-3: idempotency_key dedup ──────────────────────────────────────

    def test_notify_owner_without_key_always_inserts(self):
        """
        Default behaviour (idempotency_key='') is completely unchanged:
        every call inserts fresh rows, even if called twice with identical
        arguments — this matches every pre-existing call site that never
        passes a key.
        """
        notify_owner(self.tenant, 'info', 'Repeatable', 'Body')
        notify_owner(self.tenant, 'info', 'Repeatable', 'Body')
        count = Notification.objects.filter(
            tenant=self.tenant, title='Repeatable',
        ).count()
        # 2 owners/managers x 2 calls = 4 rows, not deduplicated
        self.assertEqual(count, 4)

    def test_notify_owner_with_same_key_is_idempotent(self):
        """
        M-3 fix: calling notify_owner() twice with the same
        idempotency_key for the same tenant/notification_type must
        result in exactly one notification per owner/manager — simulating
        a Celery task retry (notify_owner_async) firing twice for the
        same source event (e.g. the same booking id).
        """
        notify_owner(
            self.tenant, 'booking_confirmed', 'New Booking', 'Arben booked.',
            idempotency_key='booking:abc-123',
        )
        notify_owner(
            self.tenant, 'booking_confirmed', 'New Booking', 'Arben booked.',
            idempotency_key='booking:abc-123',
        )
        count = Notification.objects.filter(
            tenant=self.tenant, idempotency_key='booking:abc-123',
        ).count()
        # Still just 2 (one per owner/manager), not 4 — the retry was a no-op.
        self.assertEqual(count, 2)

    def test_notify_owner_with_different_keys_both_insert(self):
        """A different idempotency_key for a genuinely different source
        event must NOT be treated as a duplicate."""
        notify_owner(
            self.tenant, 'booking_confirmed', 'New Booking', 'First booking.',
            idempotency_key='booking:first',
        )
        notify_owner(
            self.tenant, 'booking_confirmed', 'New Booking', 'Second booking.',
            idempotency_key='booking:second',
        )
        count = Notification.objects.filter(
            tenant=self.tenant, notification_type='booking_confirmed',
        ).count()
        self.assertEqual(count, 4)  # 2 owners/managers x 2 distinct events


# ── API tests ─────────────────────────────────────────────────────────────────

class NotificationAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('apibiz')
        self.user = make_user('user@apibiz.com', self.tenant, 'owner')
        self.other_user = make_user('other@apibiz.com', self.tenant, 'customer')
        self.client.defaults['HTTP_HOST'] = 'apibiz.bizal.al'

        # Create some notifications
        Notification.objects.create(
            tenant=self.tenant, user=self.user,
            notification_type='info', title='N1', body='Body 1',
        )
        Notification.objects.create(
            tenant=self.tenant, user=self.user,
            notification_type='booking_confirmed', title='N2', body='Body 2',
        )
        Notification.objects.create(
            tenant=self.tenant, user=self.other_user,
            notification_type='info', title='Other', body='Hidden',
        )

    def test_user_sees_own_notifications(self):
        self.client.force_authenticate(user=self.user)
        resp = self.client.get('/api/notifications/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        titles = [n['title'] for n in ((resp.data['results'] if isinstance(resp.data, dict) else resp.data))]
        self.assertIn('N1', titles)
        self.assertIn('N2', titles)
        self.assertNotIn('Other', titles)

    def test_unread_count(self):
        self.client.force_authenticate(user=self.user)
        resp = self.client.get('/api/notifications/unread-count/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['unread_count'], 2)

    def test_mark_all_read_zeroes_count(self):
        self.client.force_authenticate(user=self.user)
        self.client.post('/api/notifications/mark-all-read/')
        resp = self.client.get('/api/notifications/unread-count/')
        self.assertEqual(resp.data['unread_count'], 0)

    def test_mark_single_read(self):
        n = Notification.objects.filter(user=self.user).first()
        self.client.force_authenticate(user=self.user)
        resp = self.client.post(f'/api/notifications/{n.pk}/read/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        n.refresh_from_db()
        self.assertTrue(n.is_read)

    def test_mark_other_users_notification_not_found(self):
        n = Notification.objects.get(user=self.other_user)
        self.client.force_authenticate(user=self.user)
        resp = self.client.post(f'/api/notifications/{n.pk}/read/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_unauthenticated_cannot_list(self):
        resp = self.client.get('/api/notifications/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_unauthenticated_cannot_get_unread_count(self):
        resp = self.client.get('/api/notifications/unread-count/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


# ── Celery task tests ──────────────────────────────────────────────────────────

import datetime
from unittest.mock import patch
from django.test import TestCase, override_settings
from django.utils import timezone


@override_settings(
    # CELERY_TASK_ALWAYS_EAGER is already set in test.py (runs tasks inline),
    # but we make it explicit here so the tests are self-contained and
    # readable without needing to know the settings file.
    CELERY_TASK_ALWAYS_EAGER=True,
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
)
class SendAppointmentRemindersTaskTests(TestCase):
    """
    Tests for notifications.tasks.send_appointment_reminders.

    Verifies:
      - Only appointments for *active* tenants are included (cross-tenant fix).
      - Guest-email path and user-email path both result in a send.
      - Appointments for inactive tenants are silently skipped.
      - Appointments with no contact email are skipped without error.
    """

    def setUp(self):
        self.active_tenant = Tenant.objects.create(
            name='Active Biz', slug='active-biz', business_type='clinic',
            plan='pro', is_active=True,
        )
        self.inactive_tenant = Tenant.objects.create(
            name='Inactive Biz', slug='inactive-biz', business_type='clinic',
            plan='pro', is_active=False,
        )
        from appointments.models import ServiceProvider, Service, Appointment
        provider = ServiceProvider.objects.create(
            tenant=self.active_tenant, name='Dr. A', is_active=True,
        )
        service = Service.objects.create(
            tenant=self.active_tenant, name='Check', duration_minutes=30, price=1000, is_active=True,
        )
        self.tomorrow = datetime.date.today() + datetime.timedelta(days=1)

        # Appointment for active tenant — guest email path
        self.appt_active_guest = Appointment.objects.create(
            tenant=self.active_tenant, service=service, provider=provider,
            date=self.tomorrow, start_time=datetime.time(9, 0),
            end_time=datetime.time(9, 30), status='confirmed',
            guest_name='Arta', guest_email='arta@guest.com',
        )
        # Appointment for inactive tenant — must be skipped
        provider_i = ServiceProvider.objects.create(
            tenant=self.inactive_tenant, name='Dr. I', is_active=True,
        )
        service_i = Service.objects.create(
            tenant=self.inactive_tenant, name='Check', duration_minutes=30, price=1000, is_active=True,
        )
        self.appt_inactive = Appointment.objects.create(
            tenant=self.inactive_tenant, service=service_i, provider=provider_i,
            date=self.tomorrow, start_time=datetime.time(10, 0),
            end_time=datetime.time(10, 30), status='confirmed',
            guest_name='Bardhyl', guest_email='bardhyl@inactive.com',
        )
        # Appointment with no contact at all — must not crash
        self.appt_no_contact = Appointment.objects.create(
            tenant=self.active_tenant, service=service, provider=provider,
            date=self.tomorrow, start_time=datetime.time(11, 0),
            end_time=datetime.time(11, 30), status='confirmed',
        )

    @patch('notifications.tasks.send_mail')
    def test_sends_only_to_active_tenant_appointments(self, mock_mail):
        from notifications.tasks import send_appointment_reminders
        send_appointment_reminders()
        # Only the active-tenant guest appointment has an email; inactive skipped
        self.assertEqual(mock_mail.call_count, 1)
        called_to = mock_mail.call_args[1]['recipient_list']
        self.assertIn('arta@guest.com', called_to)

    @patch('notifications.tasks.send_mail')
    def test_inactive_tenant_appointment_not_emailed(self, mock_mail):
        from notifications.tasks import send_appointment_reminders
        send_appointment_reminders()
        all_recipients = [
            addr
            for call in mock_mail.call_args_list
            for addr in call[1].get('recipient_list', [])
        ]
        self.assertNotIn('bardhyl@inactive.com', all_recipients)

    @patch('notifications.tasks.send_mail')
    def test_no_contact_appointment_skipped_silently(self, mock_mail):
        """Appointment with no user and no guest_email must not raise."""
        from notifications.tasks import send_appointment_reminders
        try:
            send_appointment_reminders()
        except Exception as exc:
            self.fail(f'send_appointment_reminders raised unexpectedly: {exc}')

    @patch('notifications.tasks.send_mail')
    def test_user_email_path(self, mock_mail):
        """Appointment linked to an authenticated user uses user.email."""
        from appointments.models import Appointment, Service, ServiceProvider
        user = User.objects.create_user(
            email='logedin@biz.com', password='pass', tenant=self.active_tenant, role='customer',
        )
        service = Service.objects.create(
            tenant=self.active_tenant, name='User Svc', duration_minutes=30, price=500, is_active=True,
        )
        provider = ServiceProvider.objects.create(
            tenant=self.active_tenant, name='Dr. U', is_active=True,
        )
        Appointment.objects.create(
            tenant=self.active_tenant, service=service, provider=provider,
            user=user, date=self.tomorrow,
            start_time=datetime.time(14, 0), end_time=datetime.time(14, 30),
            status='confirmed',
        )
        from notifications.tasks import send_appointment_reminders
        send_appointment_reminders()
        all_recipients = [
            addr
            for call in mock_mail.call_args_list
            for addr in call[1].get('recipient_list', [])
        ]
        self.assertIn('logedin@biz.com', all_recipients)

    @patch('notifications.tasks.send_mail')
    def test_returns_correct_sent_count(self, mock_mail):
        from notifications.tasks import send_appointment_reminders
        result = send_appointment_reminders()
        self.assertIn('1', result)  # "Sent 1 appointment reminders."


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
)
class ExpireTrialsTaskTests(TestCase):
    """Tests for tenants.tasks.expire_trials."""

    def setUp(self):
        from tenants.models import Tenant, PLAN_TRIAL
        self.expired_tenant = Tenant.objects.create(
            name='Expired Co', slug='expired-co', business_type='restaurant',
            plan=PLAN_TRIAL, is_active=True,
            trial_ends_at=timezone.now() - datetime.timedelta(days=1),
        )
        self.valid_tenant = Tenant.objects.create(
            name='Valid Co', slug='valid-co', business_type='restaurant',
            plan=PLAN_TRIAL, is_active=True,
            trial_ends_at=timezone.now() + datetime.timedelta(days=7),
        )

    def test_expired_trial_deactivated_without_plan_downgrade(self):
        """
        Regression test: expire_trials() must NOT change `plan` away from
        PLAN_TRIAL. See tenants/tasks.py::expire_trials and
        tenants/middleware.py::_enforce_trial for why — `trial_expired`
        only reports True while plan == PLAN_TRIAL, so downgrading the
        plan here would silently break that signal for the frontend the
        moment this task ran. Only `is_active` should change.
        """
        from tenants.tasks import expire_trials
        from tenants.models import PLAN_TRIAL
        expire_trials()
        self.expired_tenant.refresh_from_db()
        self.assertEqual(self.expired_tenant.plan, PLAN_TRIAL)
        self.assertFalse(self.expired_tenant.is_active)
        self.assertTrue(self.expired_tenant.trial_expired)

    def test_valid_trial_not_touched(self):
        from tenants.tasks import expire_trials
        from tenants.models import PLAN_TRIAL
        expire_trials()
        self.valid_tenant.refresh_from_db()
        self.assertEqual(self.valid_tenant.plan, PLAN_TRIAL)
        self.assertTrue(self.valid_tenant.is_active)

    @patch('tenants.tasks.send_mail')
    def test_sends_email_to_owner_on_expiry(self, mock_mail):
        User.objects.create_user(
            email='owner@expired.com', password='pass',
            tenant=self.expired_tenant, role='owner',
        )
        from tenants.tasks import expire_trials
        expire_trials()
        self.assertTrue(mock_mail.called)
        call_kwargs = mock_mail.call_args[1] if mock_mail.call_args[1] else {}
        recipients = call_kwargs.get('recipient_list', [])
        self.assertIn('owner@expired.com', recipients)
