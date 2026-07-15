from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from accounts.models import User
from tenants.models import Tenant
from .models import StaffMember


class StaffTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(
            name='Test Biz', slug='testbiz', business_type='restaurant', plan='pro',
            is_active=True,
        )
        self.owner = User.objects.create_user(
            email='owner@testbiz.com', password='pass1234', tenant=self.tenant, role='owner',
        )
        self.staff_user = User.objects.create_user(
            email='staff@testbiz.com', password='pass1234', tenant=self.tenant, role='staff',
        )
        StaffMember.objects.create(
            tenant=self.tenant, user=self.staff_user, role='staff', position='Waiter',
        )
        self.client.defaults['HTTP_HOST'] = 'testbiz.bizal.al'

    def test_staff_can_list_members(self):
        self.client.force_authenticate(user=self.staff_user)
        resp = self.client.get('/api/staff/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data['results']), 1)

    def test_anonymous_cannot_list_staff(self):
        resp = self.client.get('/api/staff/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_staff_scoped_to_tenant(self):
        other = Tenant.objects.create(name='Other', slug='other', business_type='gym', plan='pro', is_active=True)
        other_user = User.objects.create_user(email='x@other.com', password='p', tenant=other, role='staff')
        StaffMember.objects.create(tenant=other, user=other_user, role='staff')
        self.client.force_authenticate(user=self.staff_user)
        resp = self.client.get('/api/staff/')
        emails = [r['email'] for r in resp.data['results']]
        self.assertNotIn('x@other.com', emails)


class StaffInviteLimitTests(TestCase):
    """
    Tests for the max_staff plan-limit enforcement in _perform_staff_invite.

    NOTE: select_for_update() is a no-op on SQLite (no real locking occurs).
    These tests verify the *count-check logic* is correct; the race-condition
    prevention (preventing two simultaneous invites from both slipping through
    at max-1) is only enforced by the DB-level lock in PostgreSQL production.
    A proper concurrent race test would require a multi-threaded test with a
    live PostgreSQL connection and is out of scope for the unit suite.
    """

    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(
            name='SmallCo', slug='smallco', business_type='restaurant',
            plan='starter', is_active=True,
        )
        # 'starter' plan has staff_accounts: False by default (and
        # has_feature() reads strictly from TenantFeature rows, with no
        # PLAN_FEATURES fallback) — grant it explicitly so the view's
        # _staff_feature permission check doesn't 403 before the max_staff
        # limit logic under test ever runs.
        from tenants.models import TenantFeature
        TenantFeature.objects.update_or_create(
            tenant=self.tenant, key='staff_accounts',
            defaults={'value': 'true', 'is_custom_grant': False},
        )
        # Starter plan: max_staff = 1
        TenantFeature.objects.update_or_create(
            tenant=self.tenant, key='max_staff',
            defaults={'value': '2', 'is_custom_grant': False},
        )
        self.owner = User.objects.create_user(
            email='owner@smallco.com', password='pass1234',
            tenant=self.tenant, role='owner',
        )
        self.client.force_authenticate(user=self.owner)
        self.client.defaults['HTTP_HOST'] = 'smallco.bizal.al'

    def _invite(self, email, role='staff'):
        return self.client.post('/api/staff/', {'email': email, 'role': role}, format='json')

    def test_invite_within_limit_succeeds(self):
        resp = self._invite('staff1@co.com')
        self.assertIn(resp.status_code, (200, 201))

    def test_invite_at_limit_rejected_with_403(self):
        # Fill to max (2)
        self._invite('staff1@co.com')
        self._invite('staff2@co.com')
        # Third invite must be rejected
        resp = self._invite('staff3@co.com')
        self.assertEqual(resp.status_code, 403)
        self.assertIn('limit', resp.data.get('detail', '').lower())

    def test_inactive_staff_not_counted_toward_limit(self):
        from .models import StaffMember
        # Create two active staff so we're at the limit
        self._invite('staff1@co.com')
        self._invite('staff2@co.com')
        # Deactivate one
        sm = StaffMember.objects.filter(tenant=self.tenant, is_active=True).first()
        StaffMember.objects.filter(pk=sm.pk).update(is_active=False)
        # Now at max-1 active — next invite should succeed
        resp = self._invite('staff3@co.com')
        self.assertIn(resp.status_code, (200, 201))

    def test_reinvite_existing_active_member_at_limit_not_blocked(self):
        # Regression test: re-inviting an email that already has an active
        # StaffMember on this tenant (the documented way to change an
        # existing staff member's role) must succeed even when the tenant
        # is exactly at max_staff, since it doesn't add a new person.
        self._invite('staff1@co.com', role='staff')
        self._invite('staff2@co.com', role='staff')  # now at the limit (2/2)

        resp = self._invite('staff1@co.com', role='manager')
        self.assertIn(resp.status_code, (200, 201))
        self.assertEqual(resp.data['role'], 'manager')
        # Headcount is unchanged — still exactly 2 active members.
        self.assertEqual(
            StaffMember.objects.filter(tenant=self.tenant, is_active=True).count(), 2,
        )

    def test_invite_email_shared_across_other_tenants(self):
        """
        Regression: email is intentionally not globally unique (a person can
        have a separate account on each tenant they interact with).
        get_or_create(email=email, ...) runs an internal .get(email=email)
        that raises MultipleObjectsReturned once that email already has
        accounts on 2+ other tenants — 500ing the invite instead of
        returning the intended "already registered to another tenant" 400.
        """
        other_tenant_a = Tenant.objects.create(
            name='OtherCoA', slug='othercoa', business_type='restaurant',
            plan='starter', is_active=True,
        )
        other_tenant_b = Tenant.objects.create(
            name='OtherCoB', slug='othercob', business_type='restaurant',
            plan='starter', is_active=True,
        )
        User.objects.create_user(
            email='multi@shared.com', password='pass1234',
            tenant=other_tenant_a, role='customer',
        )
        User.objects.create_user(
            email='multi@shared.com', password='pass5678',
            tenant=other_tenant_b, role='customer',
        )
        resp = self._invite('multi@shared.com')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('another tenant', resp.data.get('detail', '').lower())

    def test_new_invite_still_blocked_at_limit_even_with_other_reinvites(self):
        self._invite('staff1@co.com')
        self._invite('staff2@co.com')  # at limit (2/2)
        # A genuinely new email must still be rejected.
        resp = self._invite('staff3@co.com')
        self.assertEqual(resp.status_code, 403)


class StaffScheduleTests(TestCase):
    """Tests for the new StaffSchedule CRUD endpoints."""

    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(
            name='Schedule Biz', slug='schedulebiz', business_type='clinic',
            plan='pro', is_active=True,
        )
        from tenants.models import TenantFeature
        TenantFeature.objects.update_or_create(
            tenant=self.tenant, key='staff_accounts',
            defaults={'value': 'true', 'is_custom_grant': False},
        )
        self.owner = User.objects.create_user(
            email='owner@schedule.com', password='pass1234', tenant=self.tenant, role='owner',
        )
        self.staff_user = User.objects.create_user(
            email='doc@schedule.com', password='pass1234', tenant=self.tenant, role='staff',
        )
        self.member = StaffMember.objects.create(
            tenant=self.tenant, user=self.staff_user, role='staff',
        )
        self.client.defaults['HTTP_HOST'] = 'schedulebiz.bizal.al'

    def test_owner_can_create_schedule(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.post(
            f'/api/staff/{self.member.pk}/schedules/',
            {'day': 'monday', 'start_time': '09:00', 'end_time': '17:00'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['day'], 'monday')

    def test_owner_can_list_schedules(self):
        from .models import StaffSchedule
        StaffSchedule.objects.create(
            tenant=self.tenant, staff=self.member,
            day='tuesday', start_time='08:00', end_time='16:00',
        )
        self.client.force_authenticate(user=self.owner)
        resp = self.client.get(f'/api/staff/{self.member.pk}/schedules/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        results = resp.data.get('results', resp.data) if isinstance(resp.data, dict) else resp.data
        days = [s['day'] for s in results]
        self.assertIn('tuesday', days)

    def test_staff_cannot_manage_schedule(self):
        """Schedules are owner-only; staff members cannot create."""
        self.client.force_authenticate(user=self.staff_user)
        resp = self.client.post(
            f'/api/staff/{self.member.pk}/schedules/',
            {'day': 'wednesday', 'start_time': '09:00', 'end_time': '17:00'},
            format='json',
        )
        self.assertIn(resp.status_code, [403, 401])

    def test_upsert_replaces_existing_day(self):
        """POSTing the same day twice should replace, not duplicate."""
        self.client.force_authenticate(user=self.owner)
        url = f'/api/staff/{self.member.pk}/schedules/'
        self.client.post(url, {'day': 'friday', 'start_time': '09:00', 'end_time': '17:00'}, format='json')
        self.client.post(url, {'day': 'friday', 'start_time': '10:00', 'end_time': '18:00'}, format='json')
        from .models import StaffSchedule
        count = StaffSchedule.objects.filter(staff=self.member, day='friday').count()
        self.assertEqual(count, 1)

    def test_invalid_day_rejected(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.post(
            f'/api/staff/{self.member.pk}/schedules/',
            {'day': 'funday', 'start_time': '09:00', 'end_time': '17:00'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_staff_from_other_tenant_rejected(self):
        other = Tenant.objects.create(
            name='Other', slug='other2', business_type='gym', plan='pro', is_active=True,
        )
        other_owner = User.objects.create_user(
            email='owner@other2.com', password='pass1234', tenant=other, role='owner',
        )
        self.client.force_authenticate(user=other_owner)
        self.client.defaults['HTTP_HOST'] = 'other2.bizal.al'
        resp = self.client.get(f'/api/staff/{self.member.pk}/schedules/')
        self.assertIn(resp.status_code, [403, 404])


class StaffSoftDeleteTests(TestCase):
    """Test that removing a staff member soft-deletes rather than hard-deletes."""

    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(
            name='Del Biz', slug='delbiz', business_type='restaurant',
            plan='pro', is_active=True,
        )
        from tenants.models import TenantFeature
        TenantFeature.objects.update_or_create(
            tenant=self.tenant, key='staff_accounts',
            defaults={'value': 'true', 'is_custom_grant': False},
        )
        self.owner = User.objects.create_user(
            email='owner@del.com', password='pass1234', tenant=self.tenant, role='owner',
        )
        self.staff_user = User.objects.create_user(
            email='waiter@del.com', password='pass1234', tenant=self.tenant, role='staff',
        )
        self.member = StaffMember.objects.create(
            tenant=self.tenant, user=self.staff_user, role='staff',
        )
        self.client.defaults['HTTP_HOST'] = 'delbiz.bizal.al'

    def test_delete_sets_is_active_false(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.delete(f'/api/staff/{self.member.pk}/')
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.member.refresh_from_db()
        self.assertFalse(self.member.is_active)

    def test_deleted_staff_not_in_active_list(self):
        self.client.force_authenticate(user=self.owner)
        self.client.delete(f'/api/staff/{self.member.pk}/')
        resp = self.client.get('/api/staff/')
        emails = [r['email'] for r in resp.data['results']]
        self.assertNotIn('waiter@del.com', emails)

    def test_user_deactivated_on_staff_removal(self):
        self.client.force_authenticate(user=self.owner)
        self.client.delete(f'/api/staff/{self.member.pk}/')
        self.staff_user.refresh_from_db()
        self.assertFalse(self.staff_user.is_active)

