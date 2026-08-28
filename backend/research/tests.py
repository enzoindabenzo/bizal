from django.contrib.admin.sites import AdminSite
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import User
from activity.utils import log_activity
from tenants.models import Tenant

from .admin import SurveyConfigAdmin
from .models import SurveyConfig, UsabilitySurveyResponse

VALID_PAYLOAD = {
    'familiar_with_bizal': False,
    'q1': 4, 'q2': 2, 'q3': 5, 'q4': 1, 'q5': 4,
    'q6': 2, 'q7': 4, 'q8': 1, 'q9': 5, 'q10': 2,
    'comments': 'Shumë e thjeshtë për t\u2019u përdorur.',
}


class UsabilitySurveyResponseModelTests(TestCase):
    def test_sus_score_formula(self):
        # Odd items (1,3,5,7,9): (answer-1). Even items (2,4,6,8,10): (5-answer).
        # All best-case answers (odd=5, even=1) -> (4*5 + 4*5) * 2.5 = 100.
        r = UsabilitySurveyResponse(
            q1=5, q3=5, q5=5, q7=5, q9=5,
            q2=1, q4=1, q6=1, q8=1, q10=1,
        )
        self.assertEqual(r.compute_sus_score(), 100.0)

    def test_sus_score_worst_case_is_zero(self):
        r = UsabilitySurveyResponse(
            q1=1, q3=1, q5=1, q7=1, q9=1,
            q2=5, q4=5, q6=5, q8=5, q10=5,
        )
        self.assertEqual(r.compute_sus_score(), 0.0)

    def test_save_snapshots_tenant_fields(self):
        tenant = Tenant.objects.create(
            name='Berberia Tirona', slug='berberia-tirona',
            business_type='barbershop', plan='trial', is_active=True,
        )
        r = UsabilitySurveyResponse.objects.create(tenant=tenant, **VALID_PAYLOAD)
        r.refresh_from_db()
        self.assertEqual(r.tenant_name_snapshot, 'Berberia Tirona')
        self.assertEqual(r.business_type_snapshot, 'barbershop')
        self.assertIsNotNone(r.sus_score)

    def test_survives_tenant_deletion(self):
        tenant = Tenant.objects.create(
            name='Deleted Later', slug='deleted-later',
            business_type='gym', plan='trial', is_active=True,
        )
        r = UsabilitySurveyResponse.objects.create(tenant=tenant, **VALID_PAYLOAD)
        tenant.delete()
        r.refresh_from_db()
        self.assertIsNone(r.tenant)
        self.assertEqual(r.tenant_name_snapshot, 'Deleted Later')


class UsabilitySurveyResponseAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(
            name='Cars SH', slug='hertz', business_type='car_rental',
            plan='enterprise', is_active=True,
        )
        self.owner = User.objects.create_user(
            email='owner@hertz.com', password='pass1234',
            tenant=self.tenant, role='owner',
        )
        self.customer = User.objects.create_user(
            email='customer@hertz.com', password='pass1234',
            tenant=self.tenant, role='customer',
        )

    def test_owner_can_submit(self):
        self.client.force_authenticate(self.owner)
        res = self.client.post('/api/research/sus/', VALID_PAYLOAD, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(UsabilitySurveyResponse.objects.count(), 1)
        row = UsabilitySurveyResponse.objects.get()
        self.assertEqual(row.tenant, self.tenant)
        self.assertIsNotNone(row.sus_score)

    def test_customer_cannot_submit(self):
        self.client.force_authenticate(self.customer)
        res = self.client.post('/api/research/sus/', VALID_PAYLOAD, format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_anonymous_cannot_submit(self):
        res = self.client.post('/api/research/sus/', VALID_PAYLOAD, format='json')
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_out_of_range_answer_rejected(self):
        self.client.force_authenticate(self.owner)
        bad = dict(VALID_PAYLOAD, q1=6)
        res = self.client.post('/api/research/sus/', bad, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_duration_pulled_from_activity_log_when_present(self):
        log_activity(
            tenant=self.tenant, actor=self.owner, verb='onboarding.completed',
            description='x', metadata={'duration_seconds': 87.3},
        )
        self.client.force_authenticate(self.owner)
        self.client.post('/api/research/sus/', VALID_PAYLOAD, format='json')
        row = UsabilitySurveyResponse.objects.get()
        self.assertEqual(row.onboarding_duration_seconds, 87.3)

    def test_duration_falls_back_when_no_activity_log(self):
        self.client.force_authenticate(self.owner)
        self.client.post('/api/research/sus/', VALID_PAYLOAD, format='json')
        row = UsabilitySurveyResponse.objects.get()
        self.assertIsNotNone(row.onboarding_duration_seconds)


class SurveyConfigModelTests(TestCase):
    def test_get_solo_creates_row_enabled_by_default(self):
        self.assertEqual(SurveyConfig.objects.count(), 0)
        cfg = SurveyConfig.get_solo()
        self.assertTrue(cfg.enabled)
        self.assertEqual(SurveyConfig.objects.count(), 1)

    def test_get_solo_returns_existing_row_not_a_new_one(self):
        SurveyConfig.get_solo().enabled = False
        SurveyConfig.objects.filter(pk=1).update(enabled=False)
        cfg = SurveyConfig.get_solo()
        self.assertFalse(cfg.enabled)
        self.assertEqual(SurveyConfig.objects.count(), 1)

    def test_save_always_pins_to_pk_1(self):
        cfg = SurveyConfig(pk=99, enabled=False)
        cfg.save()
        self.assertEqual(cfg.pk, 1)
        self.assertEqual(SurveyConfig.objects.count(), 1)

    def test_second_instance_overwrites_the_singleton_not_duplicates(self):
        SurveyConfig.objects.create(enabled=True)
        SurveyConfig.objects.create(enabled=False)
        self.assertEqual(SurveyConfig.objects.count(), 1)
        self.assertFalse(SurveyConfig.objects.get().enabled)

    def test_delete_is_a_no_op(self):
        cfg = SurveyConfig.get_solo()
        cfg.delete()
        self.assertEqual(SurveyConfig.objects.count(), 1)


class SurveyConfigAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_config_defaults_enabled_with_no_row_yet(self):
        res = self.client.get('/api/research/sus/config/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.json(), {'enabled': True})

    def test_config_reflects_disabled_flag(self):
        SurveyConfig.objects.create(enabled=False)
        res = self.client.get('/api/research/sus/config/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.json(), {'enabled': False})

    def test_config_is_public_no_auth_required(self):
        res = self.client.get('/api/research/sus/config/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)


class SurveyConfigAdminTests(TestCase):
    def setUp(self):
        self.admin = SurveyConfigAdmin(SurveyConfig, AdminSite())
        self.staff = User.objects.create_superuser(
            email='super@bizal.al', password='pass1234',
        )

    def test_add_permission_denied_once_row_exists(self):
        request = type('R', (), {'user': self.staff})()
        self.assertTrue(self.admin.has_add_permission(request))
        SurveyConfig.objects.create(enabled=True)
        self.assertFalse(self.admin.has_add_permission(request))

    def test_delete_permission_always_denied(self):
        request = type('R', (), {'user': self.staff})()
        self.assertFalse(self.admin.has_delete_permission(request))


class SurveyConfigChangelistIntegrationTests(TestCase):
    """Exercises the actual changelist_view override end-to-end (not just
    the permission methods in isolation) against a genuinely empty table."""

    def setUp(self):
        self.staff = User.objects.create_superuser(
            email='super2@bizal.al', password='pass1234',
        )

    def test_visiting_changelist_on_empty_table_auto_creates_row(self):
        from django.test import Client
        self.assertEqual(SurveyConfig.objects.count(), 0)
        c = Client()
        c.login(username='super2@bizal.al', password='pass1234')
        res = c.get('/django-admin/research/surveyconfig/')
        self.assertEqual(SurveyConfig.objects.count(), 1)
        self.assertIn(res.status_code, (200, 302))
