import datetime
from unittest.mock import patch
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from accounts.models import User
from tenants.models import Tenant
from .models import ServiceProvider, Service, Appointment


class AppointmentTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(
            name='Klinika', slug='klinika', business_type='clinic', plan='pro',
            is_active=True,
        )
        self.owner = User.objects.create_user(
            email='owner@klinika.com', password='pass1234', tenant=self.tenant, role='owner',
        )
        self.customer = User.objects.create_user(
            email='customer@klinika.com', password='pass1234', tenant=self.tenant, role='customer',
        )
        self.client.defaults['HTTP_HOST'] = 'klinika.bizal.al'
        self.provider = ServiceProvider.objects.create(
            tenant=self.tenant, name='Dr. Hoxha', title='Dermatologist', is_active=True,
        )
        self.service = Service.objects.create(
            tenant=self.tenant, name='Consultation', duration_minutes=30, price=2500, is_active=True,
        )

    def test_public_can_list_services(self):
        resp = self.client.get('/api/appointments/services/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        results = resp.data['results'] if isinstance(resp.data, dict) else resp.data
        self.assertEqual(len(results), 1)

    def test_create_appointment_auto_calculates_end_time(self):
        resp = self.client.post('/api/appointments/', {
            'service': str(self.service.pk),
            'provider': str(self.provider.pk),
            'date': '2026-09-01',
            'start_time': '10:00',
            'guest_name': 'Arben Hoxha',
            'guest_email': 'arben@test.com',
            'guest_phone': '+355691234567',
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        # 30-minute service starting at 10:00 → end_time 10:30
        self.assertEqual(resp.data['end_time'], '10:30:00')

    def test_owner_can_update_appointment_status(self):
        appt = Appointment.objects.create(
            tenant=self.tenant, service=self.service, provider=self.provider,
            date=datetime.date(2026, 9, 1), start_time=datetime.time(10, 0),
            end_time=datetime.time(10, 30), status='pending',
        )
        self.client.force_authenticate(user=self.owner)
        resp = self.client.patch(f'/api/appointments/{appt.pk}/status/', {'status': 'confirmed'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['status'], 'confirmed')

    def test_cancel_appointment(self):
        appt = Appointment.objects.create(
            tenant=self.tenant, service=self.service, provider=self.provider,
            user=self.customer, date=datetime.date(2026, 9, 1),
            start_time=datetime.time(10, 0), end_time=datetime.time(10, 30), status='confirmed',
        )
        self.client.force_authenticate(user=self.customer)
        resp = self.client.post(f'/api/appointments/{appt.pk}/cancel/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        appt.refresh_from_db()
        self.assertEqual(appt.status, 'cancelled')

    def test_owner_can_manage_services(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.post('/api/appointments/manage/services/', {
            'name': 'Full Checkup', 'duration_minutes': 60, 'price': '5000.00', 'is_active': True,
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['name'], 'Full Checkup')

    def test_anonymous_cannot_manage_services(self):
        resp = self.client.post('/api/appointments/manage/services/', {
            'name': 'Hack', 'duration_minutes': 60, 'price': '0',
        })
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


class CancelAppointmentCrossTenantTests(TestCase):
    """
    Regression tests for the cross-tenant ownership bypass in cancel_appointment.

    Before fix #4: an owner of Tenant A could cancel Tenant B's appointments
    by knowing the UUID, because the view only checked request.user.role and
    never verified request.user.tenant == request.tenant.

    After fix: is_owner requires BOTH the correct role AND tenant_id match.
    """

    def setUp(self):
        self.client = APIClient()

        self.tenant_a = Tenant.objects.create(
            name='Tenant A', slug='tenant-a', business_type='clinic',
            plan='pro', is_active=True,
        )
        self.tenant_b = Tenant.objects.create(
            name='Tenant B', slug='tenant-b', business_type='clinic',
            plan='pro', is_active=True,
        )

        self.owner_a = User.objects.create_user(
            email='owner@tenant-a.com', password='pass1234',
            tenant=self.tenant_a, role='owner',
        )
        self.owner_b = User.objects.create_user(
            email='owner@tenant-b.com', password='pass1234',
            tenant=self.tenant_b, role='owner',
        )

        provider_b = ServiceProvider.objects.create(
            tenant=self.tenant_b, name='Dr. B', is_active=True,
        )
        service_b = Service.objects.create(
            tenant=self.tenant_b, name='Checkup', duration_minutes=30, price=1000, is_active=True,
        )
        self.appt_b = Appointment.objects.create(
            tenant=self.tenant_b, service=service_b, provider=provider_b,
            date=datetime.date(2026, 10, 1), start_time=datetime.time(9, 0),
            end_time=datetime.time(9, 30), status='confirmed',
        )

    def test_owner_of_tenant_a_cannot_cancel_tenant_b_appointment(self):
        """Core regression: cross-tenant cancel must be rejected with 403."""
        self.client.force_authenticate(user=self.owner_a)
        self.client.defaults['HTTP_HOST'] = 'tenant-b.bizal.al'
        resp = self.client.post(f'/api/appointments/{self.appt_b.pk}/cancel/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.appt_b.refresh_from_db()
        self.assertEqual(self.appt_b.status, 'confirmed')  # unchanged

    def test_owner_of_correct_tenant_can_cancel_own_appointment(self):
        """Sanity check: the fix must not break legitimate owner cancels."""
        self.client.force_authenticate(user=self.owner_b)
        self.client.defaults['HTTP_HOST'] = 'tenant-b.bizal.al'
        resp = self.client.post(f'/api/appointments/{self.appt_b.pk}/cancel/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.appt_b.refresh_from_db()
        self.assertEqual(self.appt_b.status, 'cancelled')

    def test_appointment_of_other_tenant_not_visible_via_own_tenant_host(self):
        """
        Attempt to cancel Tenant B's appointment while authenticated against
        Tenant A's domain — the get(pk=pk, tenant=request.tenant) should
        return 404 before the ownership check even fires.
        """
        self.client.force_authenticate(user=self.owner_a)
        self.client.defaults['HTTP_HOST'] = 'tenant-a.bizal.al'
        resp = self.client.post(f'/api/appointments/{self.appt_b.pk}/cancel/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class AppointmentNotifyAsyncTest(TestCase):
    """Booking an appointment must dispatch notify_owner_async.delay, not call
    notify_owner synchronously — the sync call blocks the HTTP response thread."""

    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(
            name='Async Clinic', slug='async-clinic', business_type='clinic',
            plan='pro', is_active=True,
        )
        self.client.defaults['HTTP_HOST'] = 'async-clinic.bizal.al'
        self.provider = ServiceProvider.objects.create(
            tenant=self.tenant, name='Dr. Test', is_active=True,
        )
        self.service = Service.objects.create(
            tenant=self.tenant, name='Consult', duration_minutes=30, price=1500, is_active=True,
        )

    @patch('appointments.views.notify_owner_async')
    def test_appointment_create_dispatches_async_notification(self, mock_task):
        resp = self.client.post('/api/appointments/', {
            'service': str(self.service.pk),
            'provider': str(self.provider.pk),
            'date': '2026-10-01',
            'start_time': '09:00',
            'guest_name': 'Test Guest',
            'guest_email': 'guest@test.com',
            'guest_phone': '+355691234567',
        })
        self.assertEqual(resp.status_code, 201, resp.data)
        mock_task.delay.assert_called_once()
        args = mock_task.delay.call_args[0]
        self.assertEqual(args[0], str(self.tenant.pk))
        self.assertEqual(args[1], 'appointment_new')

    @patch('appointments.views.notify_owner_async')
    def test_sync_notify_owner_not_called_on_appointment_create(self, mock_task):
        with patch('notifications.utils.notify_owner') as mock_sync:
            self.client.post('/api/appointments/', {
                'service': str(self.service.pk),
                'provider': str(self.provider.pk),
                'date': '2026-10-02',
                'start_time': '11:00',
                'guest_name': 'Another Guest',
            })
            mock_sync.assert_not_called()


class AppointmentBusinessHoursTest(TestCase):
    """Same day-of-week resolution as bookings: Monday-Saturday and Sunday
    can have different posted hours, so the check must use the appointment's
    actual weekday rather than a min/max across every range."""

    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(
            name='Klinika Orari', slug='klinika-orari', business_type='clinic', plan='pro',
            is_active=True,
            business_hours={
                'E Hënë - E Shtunë': '09:00 - 20:00',
                'E Diel': '10:00 - 16:00',
            },
        )
        self.client.defaults['HTTP_HOST'] = 'klinika-orari.bizal.al'
        self.provider = ServiceProvider.objects.create(
            tenant=self.tenant, name='Dr. Hoxha', title='Dermatologist', is_active=True,
        )
        self.service = Service.objects.create(
            tenant=self.tenant, name='Consultation', duration_minutes=30, price=2500, is_active=True,
        )

    def _post(self, date, start_time):
        return self.client.post('/api/appointments/', {
            'service': str(self.service.pk),
            'provider': str(self.provider.pk),
            'date': date,
            'start_time': start_time,
            'guest_name': 'Test Guest',
            'guest_email': 'guest@test.com',
        })

    def test_saturday_within_weekday_hours_accepted(self):
        resp = self._post('2026-09-05', '19:00')  # Saturday, within 09:00-20:00
        self.assertEqual(resp.status_code, 201, resp.data)

    def test_sunday_after_sunday_close_rejected(self):
        """19:00 is fine Mon-Sat but the clinic closes at 16:00 on Sunday."""
        resp = self._post('2026-09-06', '19:00')  # Sunday
        self.assertEqual(resp.status_code, 400)

    def test_sunday_within_sunday_hours_accepted(self):
        resp = self._post('2026-09-06', '11:00')  # Sunday, within 10:00-16:00
        self.assertEqual(resp.status_code, 201, resp.data)


# ── Plan-limit / feature-gating regressions ────────────────────────────────────

class AppointmentsFeatureGatingTest(TestCase):
    """
    Regression tests: Service/Provider management and public appointment
    creation must be gated on HasTenantFeature('bookings'), and Service
    creation must respect the tenant's plan max_listings cap.
    """
    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(
            name='Gateklinika', slug='gateklinika', business_type='clinic', plan='pro',
            is_active=True,
        )
        self.owner = User.objects.create_user(
            email='owner@gateklinika.com', password='pass1234', tenant=self.tenant, role='owner',
        )
        self.client.defaults['HTTP_HOST'] = 'gateklinika.bizal.al'
        self.provider = ServiceProvider.objects.create(
            tenant=self.tenant, name='Dr. Test', title='GP', is_active=True,
        )
        self.service = Service.objects.create(
            tenant=self.tenant, name='Consultation', duration_minutes=30, price=2500, is_active=True,
        )

    def test_service_create_blocked_when_plan_lacks_bookings_feature(self):
        from tenants.models import TenantFeature
        TenantFeature.objects.update_or_create(
            tenant=self.tenant, key='bookings',
            defaults={'value': 'False', 'is_custom_grant': True},
        )
        self.client.force_authenticate(user=self.owner)
        resp = self.client.post('/api/appointments/manage/services/', {
            'name': 'Blocked', 'duration_minutes': 30, 'price': '1000.00', 'is_active': True,
        })
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_appointment_create_blocked_when_plan_lacks_bookings_feature(self):
        from tenants.models import TenantFeature
        TenantFeature.objects.update_or_create(
            tenant=self.tenant, key='bookings',
            defaults={'value': 'False', 'is_custom_grant': True},
        )
        resp = self.client.post('/api/appointments/', {
            'service': str(self.service.pk),
            'provider': str(self.provider.pk),
            'date': '2026-09-01', 'start_time': '10:00',
            'guest_name': 'Guest', 'guest_email': 'guest@test.com',
        })
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_max_listings_enforced_for_services(self):
        from tenants.models import TenantFeature
        TenantFeature.objects.update_or_create(
            tenant=self.tenant, key='max_listings',
            defaults={'value': '1', 'is_custom_grant': True},
        )
        self.client.force_authenticate(user=self.owner)
        resp = self.client.post('/api/appointments/manage/services/', {
            'name': 'Overflow', 'duration_minutes': 30, 'price': '1000.00', 'is_active': True,
        })
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(Service.objects.filter(tenant=self.tenant).count(), 1)


# ── Provider schedule enforcement (staff.StaffSchedule) ─────────────────────

class ProviderScheduleEnforcementTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(
            name='Klinika 2', slug='klinika2', business_type='clinic', plan='pro',
            is_active=True,
        )
        self.owner = User.objects.create_user(
            email='owner@klinika2.com', password='pass1234', tenant=self.tenant, role='owner',
        )
        self.client.defaults['HTTP_HOST'] = 'klinika2.bizal.al'
        self.service = Service.objects.create(
            tenant=self.tenant, name='Consultation', duration_minutes=30, price=2500, is_active=True,
        )

        from staff.models import StaffMember, StaffSchedule
        self.staff_user = User.objects.create_user(
            email='dr@klinika2.com', password='pass1234', tenant=self.tenant, role='staff',
        )
        self.staff_member = StaffMember.objects.create(
            tenant=self.tenant, user=self.staff_user, role='staff', is_active=True,
        )
        # Only scheduled Tuesday 09:00-12:00. 2026-09-01 is a Tuesday.
        StaffSchedule.objects.create(
            tenant=self.tenant, staff=self.staff_member, day='tuesday',
            start_time=datetime.time(9, 0), end_time=datetime.time(12, 0),
        )
        self.scheduled_provider = ServiceProvider.objects.create(
            tenant=self.tenant, name='Dr. Scheduled', is_active=True, staff_member=self.staff_member,
        )
        self.unlinked_provider = ServiceProvider.objects.create(
            tenant=self.tenant, name='Dr. Freelance', is_active=True,
        )

    def _book(self, provider, start_time, date='2026-09-01'):
        return self.client.post('/api/appointments/', {
            'service': str(self.service.pk),
            'provider': str(provider.pk),
            'date': date,
            'start_time': start_time,
            'guest_name': 'Guest', 'guest_email': 'guest@test.com',
        })

    def test_appointment_within_schedule_succeeds(self):
        resp = self._book(self.scheduled_provider, '10:00')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_appointment_outside_schedule_hours_rejected(self):
        # Provider only works 09:00-12:00 on Tuesday; 14:00 is outside that.
        resp = self._book(self.scheduled_provider, '14:00')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('start_time', resp.data)

    def test_appointment_on_unscheduled_day_rejected(self):
        # 2026-09-02 is a Wednesday; provider has no StaffSchedule row for it.
        resp = self._book(self.scheduled_provider, '10:00', date='2026-09-02')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('start_time', resp.data)

    def test_appointment_ending_after_schedule_end_rejected(self):
        # 30-min service starting 11:45 ends 12:15, past the 12:00 cutoff.
        resp = self._book(self.scheduled_provider, '11:45')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unlinked_provider_has_no_schedule_restriction(self):
        # No staff_member link -> falls back to old (business-hours-only) behavior.
        resp = self._book(self.unlinked_provider, '20:00')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_deactivated_staff_member_blocks_booking(self):
        self.staff_member.is_active = False
        self.staff_member.save()
        resp = self._book(self.scheduled_provider, '10:00')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('provider', resp.data)

    def test_owner_can_link_provider_to_staff_member(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.patch(
            f'/api/appointments/manage/providers/{self.unlinked_provider.pk}/',
            {'staff_member': str(self.staff_member.pk)},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.unlinked_provider.refresh_from_db()
        self.assertEqual(self.unlinked_provider.staff_member_id, self.staff_member.id)
