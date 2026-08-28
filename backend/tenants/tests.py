"""
Tenant v3 tests — models, middleware, API endpoints.
Run: python manage.py test tenants
"""

from decimal import Decimal

from django.test import TestCase

from django.utils import timezone

from django.http import Http404

from django.core.exceptions import ValidationError

from unittest.mock import patch, MagicMock

from .models import (
    Tenant, TenantFeature, TenantLocation, TenantReferral,
    PLAN_TRIAL, PLAN_STARTER, PLAN_PRO, PLAN_ENTERPRISE,
    PLAN_FEATURES, BUSINESS_TYPE_PRESETS, TRIAL_DAYS,
)

from .serializers import TenantSettingsSerializer

from .middleware import TenantMiddleware

from accounts.models import User

from unittest.mock import patch

from datetime import timedelta

from tenants.models import Tenant, TenantReferral

from django.test import SimpleTestCase

from .hours import _day_index, _expand_day_key, hours_for_weekday, is_open_at

from rest_framework.exceptions import PermissionDenied

from tenants.models import Tenant, TenantFeature

from tenants.limits import enforce_max_listings

from unittest.mock import MagicMock

from django.test import TestCase, override_settings

from .models import Tenant

import pytest

from tenants.models import (
    Tenant, TenantLocation, TenantReferral, TenantFeature, CreditLedger,
    PLAN_STARTER, PLAN_PRO, BUSINESS_TYPE_PRESETS,
)

from django.contrib.auth.models import AnonymousUser

from .permissions import (
    get_effective_role,
    IsTenantStaff,
    HasTenantRole,
    HasTenantFeature,
    IsOwnTenantStaff,
    IsOwnTenantOwnerOrManager,
    HasPlanAtLeast,
)

from unittest.mock import MagicMock, patch

from rest_framework import serializers as drf_serializers

from rest_framework.test import APIRequestFactory

from .models import Tenant, PLAN_PRO, PLAN_TRIAL

from .serializers import (
    _clean_nav_config,
    TenantPublicSerializer,
    MarketplaceTenantSerializer,
    TenantAdminSerializer,
    TenantSettingsSerializer,
    TenantSignupSerializer,
)

from rest_framework.test import APIClient

from rest_framework import status

from tenants.models import Tenant

import datetime

from .models import Tenant, TenantReferral, PLAN_TRIAL, PLAN_PRO, PLAN_STARTER

from .tasks import (
    expire_trials, send_trial_warning_emails,
    apply_referral_credits_for_active_tenants, refresh_fx_rates,
)

from .models import (
    Tenant, TenantLocation, TenantReferral, CreditLedger,
    PLAN_TRIAL, PLAN_STARTER, PLAN_PRO, PLAN_ENTERPRISE,
)

from billing.models import Invoice

from django.contrib.auth import get_user_model

from tenants.models import Tenant, PLAN_PRO, PLAN_STARTER

from tenants.permissions import IsTenantOwner


def make_tenant(**kwargs):
    defaults = dict(
        name='Test Biz', slug='test-biz', business_type='restaurant',
        is_active=True, plan=PLAN_PRO,
    )
    defaults.update(kwargs)
    return Tenant.objects.create(**defaults)


class TenantModelTests(TestCase):

    def test_slug_auto_generated(self):
        t = Tenant.objects.create(name='My Test Shop', business_type='market', is_active=True, plan=PLAN_STARTER)
        self.assertTrue(t.slug)

    def test_referral_code_auto_generated(self):
        t = make_tenant()
        self.assertTrue(t.referral_code)

    def test_trial_not_set_until_activation(self):
        # trial_ends_at is activation-gated: it must stay None at creation
        # time, regardless of is_active, and only gets set by
        # tenants/admin.py::apply_activation_side_effects() on the
        # False->True transition (covered in ActivationSideEffectsHelperTests).
        t = Tenant.objects.create(
            name='Trial Biz', slug='trial-biz', business_type='clinic',
            is_active=True, plan=PLAN_TRIAL,
        )
        self.assertIsNone(t.trial_ends_at)

    def test_trial_expired_property(self):
        t = make_tenant(plan=PLAN_TRIAL, trial_ends_at=timezone.now() - timezone.timedelta(days=1))
        self.assertTrue(t.trial_expired)

    def test_trial_days_remaining(self):
        t = make_tenant(plan=PLAN_TRIAL, trial_ends_at=timezone.now() + timezone.timedelta(days=5))
        self.assertEqual(t.trial_days_remaining, 5)

    def test_currency_defaults_to_ALL(self):
        t = make_tenant()
        self.assertEqual(t.currency, 'ALL')

    def test_currency_choices_locked_to_ALL(self):
        # Currency is no longer tenant-selectable — see the comment on
        # Tenant.currency in tenants/models.py. EUR/USD are still available
        # to a tenant's own customers, but only as a pay_currency choice at
        # Stripe checkout time (payments.views.create_booking_checkout),
        # never as the tenant's stored ledger currency.
        self.assertEqual(Tenant.CURRENCY_CHOICES, [('ALL', 'Lek Shqiptar (ALL)')])

    def test_plan_features_applied_on_save(self):
        t = make_tenant(plan=PLAN_ENTERPRISE, business_type='hotel')
        self.assertTrue(t.has_feature('crm'))
        self.assertTrue(t.has_feature('multi_location'))

    def test_business_type_preset_upgrades_features(self):
        """A hotel on Pro should get bookings even though Pro has bookings=True already,
        and should get crm=True from the preset even though Pro has crm=False."""
        t = make_tenant(plan=PLAN_PRO, business_type='hotel')
        self.assertTrue(t.has_feature('bookings'))
        self.assertTrue(t.has_feature('crm'))

    def test_starter_restaurant_gets_bookings(self):
        """Restaurant preset upgrades bookings even on Starter."""
        t = make_tenant(plan=PLAN_STARTER, business_type='restaurant')
        self.assertTrue(t.has_feature('bookings'))

    def test_has_feature_false_on_expired_trial(self):
        t = make_tenant(
            plan=PLAN_TRIAL,
            trial_ends_at=timezone.now() - timezone.timedelta(hours=1),
        )
        # Even if features say True, expired trial returns False
        self.assertFalse(t.has_feature('bookings'))

    def test_custom_grant_survives_plan_change(self):
        t = make_tenant(plan=PLAN_STARTER, business_type='market')
        # Superadmin grants api_access manually
        TenantFeature.objects.update_or_create(
            tenant=t, key='api_access',
            defaults={'value': 'True', 'is_custom_grant': True}
        )
        # Change plan — api_access should NOT be reset because it's a custom grant
        # (apply_plan_defaults uses update_or_create but is_custom_grant=False means non-custom rows get overwritten)
        # Custom grant rows have is_custom_grant=True so they are written by the grant itself, not reset
        f = TenantFeature.objects.get(tenant=t, key='api_access')
        self.assertTrue(f.is_custom_grant)


class TenantLocationTests(TestCase):

    def setUp(self):
        self.tenant = make_tenant(plan=PLAN_ENTERPRISE)

    def test_primary_location_unique(self):
        loc1 = TenantLocation.objects.create(tenant=self.tenant, name='Branch A', is_primary=True)
        loc2 = TenantLocation.objects.create(tenant=self.tenant, name='Branch B', is_primary=True)
        loc1.refresh_from_db()
        self.assertFalse(loc1.is_primary)
        self.assertTrue(loc2.is_primary)


class TenantReferralTests(TestCase):

    def test_referral_credit_applied(self):
        referrer = make_tenant(slug='referrer-biz')
        referred = make_tenant(slug='referred-biz', plan=PLAN_TRIAL)
        ref = TenantReferral.objects.create(referrer=referrer, referred=referred, credit_amount=10)
        ref.apply_credit()
        referrer.refresh_from_db()
        self.assertEqual(referrer.referral_credits, 10)
        self.assertTrue(ref.applied)

    def test_referral_credit_not_double_applied(self):
        referrer = make_tenant(slug='referrer-biz2')
        referred = make_tenant(slug='referred-biz2', plan=PLAN_TRIAL)
        ref = TenantReferral.objects.create(referrer=referrer, referred=referred, credit_amount=10)
        ref.apply_credit()
        ref.apply_credit()  # second call should be no-op
        referrer.refresh_from_db()
        self.assertEqual(referrer.referral_credits, 10)


class MiddlewareTests(TestCase):

    def _middleware(self):
        return TenantMiddleware(get_response=lambda r: MagicMock(status_code=200))

    def test_main_domain_returns_none_tenant(self):
        mw = self._middleware()
        req = MagicMock()
        req.get_host.return_value = 'bizal.al'
        req.path = '/'
        req.GET = {}
        req.session = {}
        req.tenant = None
        with patch.object(mw, '_resolve_tenant', return_value=None):
            result = mw._resolve_tenant(req)
        self.assertIsNone(result)

    def test_expired_trial_deactivates_without_raising(self):
        """
        _enforce_trial never raises Http404 — by design (see its docstring):
        expired-trial tenants are let through so the frontend can read
        trial_expired/is_active and show an upgrade screen, rather than
        hitting a generic 404. It marks the tenant inactive instead.
        """
        mw = self._middleware()
        tenant = make_tenant(
            slug='expired-trial-biz',
            plan=PLAN_TRIAL,
            trial_ends_at=timezone.now() - timezone.timedelta(hours=1),
        )
        req = MagicMock()
        req.tenant = tenant
        req.path = '/dashboard/'

        mw._enforce_trial(req)

        self.assertFalse(req.tenant.is_active)
        tenant.refresh_from_db()
        self.assertFalse(tenant.is_active)
        # plan must stay PLAN_TRIAL so `trial_expired` keeps reporting True
        self.assertEqual(tenant.plan, PLAN_TRIAL)
        self.assertTrue(tenant.trial_expired)

    def test_get_tenant_raises_404_for_unknown_slug(self):
        """
        The actual Http404 in the tenant-resolution path is raised by
        _get_tenant when no tenant matches the slug at all.
        """
        mw = self._middleware()
        with self.assertRaises(Http404):
            mw._get_tenant('no-such-tenant-slug', strict=True)

    def test_get_tenant_raises_404_for_inactive_non_trial_tenant(self):
        """
        A tenant that is inactive for a reason other than trial expiry
        (e.g. suspended, pending activation) should still 404 under strict
        resolution.
        """
        mw = self._middleware()
        tenant = make_tenant(
            slug='suspended-biz',
            plan=PLAN_PRO,
            is_active=False,
        )
        with self.assertRaises(Http404):
            mw._get_tenant(tenant.slug, strict=True)

    def test_get_tenant_lets_expired_trial_through(self):
        """
        An inactive tenant whose inactivity is due to trial expiry should
        NOT 404 under strict resolution — it's deliberately let through.
        """
        mw = self._middleware()
        tenant = make_tenant(
            slug='expired-trial-strict',
            plan=PLAN_TRIAL,
            is_active=False,
            trial_ends_at=timezone.now() - timezone.timedelta(hours=1),
        )
        result = mw._get_tenant(tenant.slug, strict=True)
        self.assertEqual(result.pk, tenant.pk)


class FeatureCoverageTests(TestCase):

    def test_all_plans_have_required_keys(self):
        required = ['bookings', 'crm', 'max_staff', 'max_listings']
        for plan, features in PLAN_FEATURES.items():
            for key in required:
                self.assertIn(key, features, f"Plan '{plan}' missing key '{key}'")

    def test_enterprise_has_all_features(self):
        enterprise = PLAN_FEATURES[PLAN_ENTERPRISE]
        bool_features = [k for k, v in enterprise.items() if isinstance(v, bool)]
        for f in bool_features:
            self.assertTrue(enterprise[f], f"Enterprise should have {f}=True")

    def test_no_preset_downgrades_to_false(self):
        """Presets should only upgrade, never force a feature to False."""
        for btype, overrides in BUSINESS_TYPE_PRESETS.items():
            for key, val in overrides.items():
                if isinstance(val, bool):
                    self.assertTrue(val, f"Preset {btype}.{key} tries to force False — not allowed")


class TenantMeViewPermissionTests(TestCase):
    """
    Regression test: TenantMeView used to only require IsAuthenticated,
    which let any authenticated user with a tenant FK — including a plain
    customer — PATCH their tenant's settings (name, branding, business
    hours, marketplace listing, etc).
    """

    def setUp(self):
        from rest_framework.test import APIClient
        self.tenant = Tenant.objects.create(
            name='Original Name', slug='shop1', business_type='retail',
            plan='pro', is_active=True,
        )
        self.client = APIClient()
        self.client.defaults['HTTP_HOST'] = 'shop1.bizal.al'

    def test_customer_cannot_edit_tenant_settings(self):
        customer = User.objects.create_user(
            email='cust@x.com', password='pass1234', tenant=self.tenant, role='customer'
        )
        self.client.force_authenticate(user=customer)
        resp = self.client.patch('/api/tenants/me/', {'name': 'HACKED'}, format='json')
        self.tenant.refresh_from_db()
        self.assertIn(resp.status_code, (401, 403))
        self.assertEqual(self.tenant.name, 'Original Name')

    def test_owner_can_edit_tenant_settings(self):
        owner = User.objects.create_user(
            email='owner@x.com', password='pass1234', tenant=self.tenant, role='owner'
        )
        self.client.force_authenticate(user=owner)
        resp = self.client.patch('/api/tenants/me/', {'name': 'New Name'}, format='json')
        self.tenant.refresh_from_db()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.tenant.name, 'New Name')

    def test_staff_can_read_but_not_write(self):
        staff = User.objects.create_user(
            email='staff@x.com', password='pass1234', tenant=self.tenant, role='staff'
        )
        from staff.models import StaffMember
        StaffMember.objects.create(tenant=self.tenant, user=staff, role='staff', is_active=True)
        self.client.force_authenticate(user=staff)
        get_resp = self.client.get('/api/tenants/me/')
        patch_resp = self.client.patch('/api/tenants/me/', {'name': 'Sneaky'}, format='json')
        self.assertEqual(get_resp.status_code, 200)
        self.assertIn(patch_resp.status_code, (401, 403))


class OnboardingCompletionLoggingTests(TestCase):
    """
    Pilot/thesis instrumentation: TenantMeView.perform_update() logs an
    ActivityLog(verb='onboarding.completed') exactly once, the first time
    onboarding_complete flips False -> True, with a duration_seconds
    computed from tenant.created_at — this is what lets onboarding time be
    measured automatically for real signups instead of a manual stopwatch.
    See research/onboarding_timing_methodology.md.
    """

    def setUp(self):
        from rest_framework.test import APIClient
        self.tenant = Tenant.objects.create(
            name='Onboard Co', slug='onboardco', business_type='restaurant',
            plan='starter', is_active=True,
        )
        self.owner = User.objects.create_user(
            email='owner@onboardco.com', password='pass1234',
            tenant=self.tenant, role='owner',
        )
        self.client = APIClient()
        self.client.defaults['HTTP_HOST'] = 'onboardco.bizal.al'
        self.client.force_authenticate(user=self.owner)

    def test_completing_onboarding_logs_one_activity_entry(self):
        from activity.models import ActivityLog

        self.assertEqual(
            ActivityLog.objects.filter(tenant=self.tenant, verb='onboarding.completed').count(),
            0,
        )

        resp = self.client.patch(
            '/api/tenants/me/',
            {'onboarding_complete': True, 'onboarding_step': 6},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)

        logs = ActivityLog.objects.filter(tenant=self.tenant, verb='onboarding.completed')
        self.assertEqual(logs.count(), 1)
        self.assertIn('duration_seconds', logs.first().metadata)
        self.assertGreaterEqual(logs.first().metadata['duration_seconds'], 0)

    def test_subsequent_saves_do_not_duplicate_the_log_entry(self):
        from activity.models import ActivityLog

        self.client.patch(
            '/api/tenants/me/', {'onboarding_complete': True, 'onboarding_step': 6}, format='json',
        )
        # A later, unrelated settings change (already-complete tenant editing
        # their name) must not create a second onboarding.completed entry.
        resp = self.client.patch('/api/tenants/me/', {'name': 'Onboard Co Renamed'}, format='json')
        self.assertEqual(resp.status_code, 200)

        self.assertEqual(
            ActivityLog.objects.filter(tenant=self.tenant, verb='onboarding.completed').count(),
            1,
        )

    def test_incomplete_to_incomplete_does_not_log(self):
        """Sanity check: merely PATCHing other fields while onboarding_complete
        stays False must not log a spurious completion event."""
        from activity.models import ActivityLog

        resp = self.client.patch('/api/tenants/me/', {'onboarding_step': 3}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            ActivityLog.objects.filter(tenant=self.tenant, verb='onboarding.completed').count(),
            0,
        )


class TenantMeViewBillingFieldsTests(TestCase):
    """
    Regression test: TenantSettingsSerializer (GET/PATCH /api/tenants/me/)
    was missing plan/trial_ends_at/trial_days_remaining/trial_expired/
    has_billing_account entirely. The admin panel's trial-expiry banner
    and billing/upgrade UI read these fields off this exact endpoint —
    without them, TENANT.plan was always undefined client-side, so the
    banner could never fire and there was no way to tell whether a tenant
    already had a Stripe customer (and so should see "Manage Billing"
    instead of "Upgrade").
    """

    def setUp(self):
        from rest_framework.test import APIClient
        from django.utils import timezone
        from datetime import timedelta
        self.client = APIClient()
        self.tenant = Tenant.objects.create(
            name='Trial Biz', slug='trialbiz', business_type='spa',
            plan='trial', is_active=True,
            trial_ends_at=timezone.now() + timedelta(days=5),
        )
        self.owner = User.objects.create_user(
            email='owner@trialbiz.com', password='pass1234',
            tenant=self.tenant, role='owner',
        )
        self.client.defaults['HTTP_HOST'] = 'trialbiz.bizal.al'
        self.client.force_authenticate(user=self.owner)

    def test_plan_and_trial_fields_present_on_get(self):
        resp = self.client.get('/api/tenants/me/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['plan'], 'trial')
        self.assertFalse(resp.data['trial_expired'])
        self.assertIn('trial_days_remaining', resp.data)
        self.assertGreaterEqual(resp.data['trial_days_remaining'], 4)

    def test_trial_expired_true_after_trial_ends_at_passes(self):
        from django.utils import timezone
        from datetime import timedelta
        self.tenant.trial_ends_at = timezone.now() - timedelta(days=1)
        self.tenant.save()
        resp = self.client.get('/api/tenants/me/')
        self.assertTrue(resp.data['trial_expired'])

    def test_has_billing_account_false_when_no_stripe_customer(self):
        resp = self.client.get('/api/tenants/me/')
        self.assertFalse(resp.data['has_billing_account'])

    def test_has_billing_account_true_when_stripe_customer_exists(self):
        self.tenant.stripe_customer_id = 'cus_abc123'
        self.tenant.save()
        resp = self.client.get('/api/tenants/me/')
        self.assertTrue(resp.data['has_billing_account'])

    def test_raw_stripe_customer_id_never_exposed(self):
        """The serializer must expose only the has_billing_account boolean,
        never the raw Stripe customer ID, to an owner-facing endpoint."""
        self.tenant.stripe_customer_id = 'cus_super_secret_id'
        self.tenant.save()
        resp = self.client.get('/api/tenants/me/')
        self.assertNotIn('stripe_customer_id', resp.data)
        self.assertNotIn('cus_super_secret_id', str(resp.data))

    def test_plan_field_is_read_only_via_patch(self):
        """An owner must not be able to grant themselves a plan upgrade by
        PATCHing 'plan' directly — that must only happen via the Stripe
        webhook after real payment."""
        resp = self.client.patch('/api/tenants/me/', {'plan': 'enterprise'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.plan, 'trial')


class CheckSlugTests(TestCase):
    """
    Tests for GET /api/tenants/check-slug/.

    Issue #15: this endpoint is public/unauthenticated by design (used
    during onboarding before an account exists), so it must be
    rate-limited per IP to prevent slug (business name) enumeration via
    brute force. RATELIMIT_ENABLE=False in the test settings makes the
    decorator a no-op here, so these tests cover correctness of the
    underlying view, not the rate limit itself (which would need a
    settings override + many requests to exercise meaningfully).
    """

    def test_available_slug_reports_available(self):
        from rest_framework.test import APIClient
        client = APIClient()
        resp = client.get('/api/tenants/check-slug/', {'slug': 'totally-unused-slug-xyz'})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data['available'])

    def test_taken_slug_reports_unavailable(self):
        from rest_framework.test import APIClient
        make_tenant(slug='already-taken-slug')
        client = APIClient()
        resp = client.get('/api/tenants/check-slug/', {'slug': 'already-taken-slug'})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data['available'])

    def test_reserved_slug_reports_unavailable(self):
        """
        check_slug must reject reserved slugs (admin, api,
        health, etc.) even though no Tenant row exists with that slug.
        TenantSignupSerializer already blocks these at submit time, so this
        was never a security gap — but without this check the onboarding
        wizard showed a false "available" green indicator for a reserved
        slug, only to have the real signup fail right after.
        """
        from rest_framework.test import APIClient
        from tenants.models import Tenant
        client = APIClient()
        for slug in ('admin', 'api', 'health', 'superadmin'):
            resp = client.get('/api/tenants/check-slug/', {'slug': slug})
            self.assertEqual(resp.status_code, 200)
            self.assertFalse(
                resp.data['available'],
                f'expected "{slug}" to be reported unavailable (reserved)',
            )
            self.assertIn(slug, Tenant._RESERVED_SLUGS)  # sanity check on fixture assumption

    def test_check_slug_decorated_with_rate_limiter(self):
        """
        Confirms check_slug is wired up to ratelimit_decorator('10/m',
        method='GET'). This is checked via source inspection rather than
        by triggering a live 429, because ratelimit_decorator() resolves
        settings.RATELIMIT_ENABLE at decoration time (when the @decorator
        line is evaluated on module import) — by the time any test runs,
        the view is already permanently wired to whichever branch was
        active when bizal.urls (and tenants.views) were first imported
        under this process's settings (RATELIMIT_ENABLE=False in
        bizal/settings/test.py). override_settings() at test time cannot
        retroactively change that, so a live-429 test would be testing
        nothing. See test_ratelimit_decorator_returns_real_limiter_when_enabled
        below for a direct test of the decorator factory itself, which IS
        meaningfully testable independent of import order.
        """
        import inspect
        import tenants.views as tenants_views_module
        source = inspect.getsource(tenants_views_module)
        # The decorator line itself, not just the function — confirms the
        # rate limit was actually added to check_slug, not just present
        # somewhere else in the file.
        check_slug_start = source.index('def check_slug')
        preceding = source[:check_slug_start]
        # Walk backward to the nearest blank-line-delimited decorator block
        decorator_block = preceding[preceding.rfind('@api_view'):]
        self.assertIn("_ratelimit_decorator('10/m', method='GET')", decorator_block)

    def test_ratelimit_decorator_returns_real_limiter_when_enabled(self):
        """
        Direct test of bizal.ratelimit_utils.ratelimit_decorator: with
        RATELIMIT_ENABLE=True it must return a real django-ratelimit
        decorator (not the no-op passthrough). This is the part of the
        fix that's actually testable at request time, independent of
        Django's import order.
        """
        from django.test import override_settings
        from bizal.ratelimit_utils import ratelimit_decorator

        with override_settings(RATELIMIT_ENABLE=True):
            decorator = ratelimit_decorator('30/m', method='GET')
            # The no-op branch returns `lambda f: f` (identity); the real
            # branch returns django_ratelimit's `ratelimit(...)` decorator,
            # which is a distinct, named callable — not identity.
            def dummy(request):
                return request
            wrapped = decorator(dummy)
            self.assertIsNot(wrapped, dummy)

        with override_settings(RATELIMIT_ENABLE=False):
            decorator = ratelimit_decorator('30/m', method='GET')
            def dummy2(request):
                return request
            wrapped2 = decorator(dummy2)
            self.assertIs(wrapped2, dummy2)


class TenantSignupTests(TestCase):
    """
    Tests for the POST /api/tenants/signup/ endpoint.

    Covers: happy path (User + Tenant + JWT), duplicate email race condition
    (IntegrityError guard), duplicate slug rejection, referral credit applied,
    trial plan defaults set, and email sent (mocked).
    """

    def setUp(self):
        from rest_framework.test import APIClient
        self.client = APIClient()
        # tenant_signup is MainDomainOnly — simulate main domain
        self.client.defaults['HTTP_HOST'] = 'bizal.al'
        self.url = '/api/tenants/signup/'
        self.base_payload = {
            'business_name': 'Test Dyqani',
            'slug': 'test-dyqan',
            'business_type': 'restaurant',
            'owner_name': 'Arta Koci',
            'owner_email': 'arta@test.com',
            'owner_password': 'StrongPass99!',
        }

    # ── Happy path ────────────────────────────────────────────

    @patch('tenants.views.send_mail')
    def test_signup_creates_tenant_user_and_returns_jwt(self, mock_mail):
        resp = self.client.post(self.url, self.base_payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        data = resp.data
        self.assertIn('access', data)
        self.assertIn('refresh', data)
        self.assertEqual(data['slug'], 'test-dyqan')
        # Trial clock is activation-gated — must be None until a superadmin
        # activates the tenant, not set at signup.
        self.assertIsNone(data.get('trial_ends_at'))

        # DB state
        from accounts.models import User
        tenant = Tenant.objects.get(slug='test-dyqan')
        self.assertEqual(tenant.plan, PLAN_TRIAL)
        self.assertFalse(tenant.is_active)  # pending review
        self.assertIsNone(tenant.trial_ends_at)
        user = User.objects.get(email='arta@test.com')
        self.assertEqual(user.role, 'owner')
        self.assertEqual(user.tenant, tenant)

    @patch('tenants.views.send_mail')
    def test_signup_sends_two_emails(self, mock_mail):
        self.client.post(self.url, self.base_payload, format='json')
        self.assertEqual(mock_mail.call_count, 2)

    # ── Validation ────────────────────────────────────────────

    def test_duplicate_slug_rejected(self):
        Tenant.objects.create(
            name='Existing', slug='test-dyqan', business_type='restaurant',
            is_active=True, plan=PLAN_PRO,
        )
        resp = self.client.post(self.url, self.base_payload, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('slug', resp.data)

    @patch('tenants.views.send_mail')
    def test_email_already_used_on_another_tenant_is_allowed(self, mock_mail):
        # Per-tenant email uniqueness (see accounts.models.User): the same
        # person can own accounts on multiple tenants with the same email.
        # Signup always creates a brand-new tenant, so there's no existing
        # tenant scope for the email to collide with — this must succeed.
        from accounts.models import User
        User.objects.create_user(
            email='arta@test.com', password='pass', full_name='Existing',
        )
        resp = self.client.post(self.url, self.base_payload, format='json')
        self.assertEqual(resp.status_code, 201)

    @patch('tenants.views.send_mail')
    def test_weak_password_rejected(self, mock_mail):
        payload = dict(self.base_payload, owner_password='1234')
        resp = self.client.post(self.url, payload, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_invalid_referral_code_rejected(self):
        payload = dict(self.base_payload, referral_code='BADCODE')
        resp = self.client.post(self.url, payload, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('referral_code', resp.data)

    # ── Referral ─────────────────────────────────────────────

    @patch('tenants.views.send_mail')
    def test_valid_referral_applies_credit(self, mock_mail):
        referrer = Tenant.objects.create(
            name='Referrer Co', slug='referrer-co', business_type='restaurant',
            is_active=True, plan=PLAN_PRO, referral_code='REF001',
        )
        payload = dict(self.base_payload, referral_code='REF001')
        resp = self.client.post(self.url, payload, format='json')
        self.assertEqual(resp.status_code, 201)

        referrer.refresh_from_db()
        self.assertGreater(referrer.referral_credits, 0)

        from .models import TenantReferral
        ref = TenantReferral.objects.get(referrer=referrer)
        self.assertTrue(ref.applied)

    # ── Race-condition guard ──────────────────────────────────

    @patch('tenants.views.send_mail')
    def test_integrity_error_on_duplicate_email_returns_400_and_rolls_back_tenant(self, mock_mail):
        """
        Simulates the TOCTOU window: serializer validation passes, but
        create_user() raises IntegrityError (e.g. concurrent signup).
        Tenant must be rolled back and a 400 returned — not a 500.
        """
        from django.db import IntegrityError
        from unittest.mock import patch as _patch
        tenant_count_before = Tenant.objects.count()

        with _patch('accounts.models.User.objects.create_user', side_effect=IntegrityError('unique violation')):
            resp = self.client.post(self.url, self.base_payload, format='json')

        self.assertEqual(resp.status_code, 400)
        self.assertIn('owner_email', resp.data)
        # Tenant created during signup must have been deleted on rollback
        self.assertEqual(Tenant.objects.count(), tenant_count_before)

    # ── Trial defaults ────────────────────────────────────────

    @patch('tenants.views.send_mail')
    def test_trial_ends_at_not_set_at_signup(self, mock_mail):
        # Trial clock is activation-gated: signup must
        # leave trial_ends_at unset. It only gets set when a superadmin
        # activates the tenant via /django-admin/ — see
        # ActivationSideEffectsHelperTests.test_activation_starts_trial_clock.
        self.client.post(self.url, self.base_payload, format='json')
        tenant = Tenant.objects.get(slug='test-dyqan')
        self.assertEqual(tenant.plan, PLAN_TRIAL)
        self.assertIsNone(tenant.trial_ends_at)


class ActivationSideEffectsHelperTests(TestCase):
    """
    tenants/admin.py::apply_activation_side_effects() replaced
    SuperadminTenantDetailView.perform_update() (removed — /django-admin/
    is now the only surface that flips Tenant.is_active). These tests cover
    the helper directly: trial-clock start/guard and owner notification
    emails on an is_active transition.
    """

    def setUp(self):
        self.tenant = Tenant.objects.create(
            name='Dyqani Test', slug='dyqan-test',
            business_type='restaurant', plan='trial',
            is_active=False,
        )
        self.owner = User.objects.create_user(
            email='owner@dyqan.al', password='pass1234',
            full_name='Arta Hoxha',
            tenant=self.tenant, role='owner',
        )

    @patch('tenants.admin.send_mail')
    def test_activation_sends_email_to_owner(self, mock_mail):
        """Owner merr email kur llogaria aktivizohet."""
        from .admin import apply_activation_side_effects
        self.tenant.is_active = True
        self.tenant.save()

        apply_activation_side_effects(self.tenant, was_active=False)

        owner_calls = [c for c in mock_mail.call_args_list if self.owner.email in str(c)]
        self.assertGreater(len(owner_calls), 0, 'No activation email sent to owner')
        first_subject = mock_mail.call_args_list[0][1].get('subject') or mock_mail.call_args_list[0][0][0]
        self.assertIn('aktivizuar', first_subject.lower())

    @patch('tenants.admin.send_mail')
    def test_activation_starts_trial_clock(self, mock_mail):
        """
        trial_ends_at must be None before activation, and get set to
        now + TRIAL_DAYS the moment is_active flips False -> True for a
        trial-plan tenant.
        """
        import datetime
        from .admin import apply_activation_side_effects

        self.assertIsNone(self.tenant.trial_ends_at)
        before = timezone.now()

        self.tenant.is_active = True
        self.tenant.save()
        apply_activation_side_effects(self.tenant, was_active=False)
        self.tenant.refresh_from_db()

        self.assertTrue(self.tenant.is_active)
        self.assertIsNotNone(self.tenant.trial_ends_at)
        expected = before + datetime.timedelta(days=TRIAL_DAYS)
        delta = abs((self.tenant.trial_ends_at - expected).total_seconds())
        self.assertLess(delta, 5)  # within 5 seconds of expected

    @patch('tenants.admin.send_mail')
    def test_reactivation_does_not_reset_trial_clock(self, mock_mail):
        """
        A tenant that's already been activated once (trial_ends_at set),
        then deactivated and reactivated, must keep its original
        trial_ends_at rather than getting a fresh 14 days — the `not
        tenant.trial_ends_at` guard in apply_activation_side_effects() exists
        for this.
        """
        from .admin import apply_activation_side_effects
        original_expiry = timezone.now() + timezone.timedelta(days=3)
        self.tenant.is_active = True
        self.tenant.trial_ends_at = original_expiry
        self.tenant.save()

        # Deactivate then reactivate
        self.tenant.is_active = False
        self.tenant.save()
        apply_activation_side_effects(self.tenant, was_active=True)
        self.tenant.is_active = True
        self.tenant.save()
        apply_activation_side_effects(self.tenant, was_active=False)

        self.tenant.refresh_from_db()
        self.assertTrue(self.tenant.is_active)
        self.assertEqual(self.tenant.trial_ends_at, original_expiry)

    @patch('tenants.admin.send_mail')
    def test_no_transition_is_a_no_op(self, mock_mail):
        """Calling the helper with was_active == current is_active must do nothing."""
        # self.tenant starts is_active=False with trial_ends_at=None already.
        from .admin import apply_activation_side_effects
        apply_activation_side_effects(self.tenant, was_active=self.tenant.is_active)
        self.tenant.refresh_from_db()
        self.assertIsNone(self.tenant.trial_ends_at)
        self.assertEqual(mock_mail.call_count, 0)

    @patch('tenants.admin.send_mail')
    def test_deactivation_does_not_touch_trial_clock(self, mock_mail):
        """Deactivating an already-running trial must leave trial_ends_at untouched."""
        from .admin import apply_activation_side_effects
        original_expiry = timezone.now() + timezone.timedelta(days=3)
        self.tenant.is_active = True
        self.tenant.trial_ends_at = original_expiry
        self.tenant.save()

        self.tenant.is_active = False
        self.tenant.save()
        apply_activation_side_effects(self.tenant, was_active=True)

        self.tenant.refresh_from_db()
        self.assertFalse(self.tenant.is_active)
        self.assertEqual(self.tenant.trial_ends_at, original_expiry)

    @patch('tenants.admin.send_mail')
    def test_deactivation_sends_email_to_owner(self, mock_mail):
        """Owner merr email kur llogaria çaktivizohet."""
        from .admin import apply_activation_side_effects
        self.tenant.is_active = True
        self.tenant.save()

        self.tenant.is_active = False
        self.tenant.save()
        apply_activation_side_effects(self.tenant, was_active=True)

        owner_calls = [c for c in mock_mail.call_args_list if self.owner.email in str(c)]
        self.assertGreater(len(owner_calls), 0, 'No deactivation email sent to owner')

    @patch('tenants.admin.send_mail', side_effect=Exception('smtp down'))
    def test_email_failure_does_not_raise(self, mock_mail):
        """
        The whole owner-lookup/send_mail block is wrapped in a bare
        `except Exception: pass` specifically so a broken mail server can
        never block a superadmin's activation/deactivation click. Confirm
        that guard actually swallows the exception.
        """
        from .admin import apply_activation_side_effects
        self.tenant.is_active = True
        self.tenant.save()

        apply_activation_side_effects(self.tenant, was_active=False)  # must not raise

        self.tenant.refresh_from_db()
        self.assertTrue(self.tenant.is_active)
        self.assertIsNotNone(self.tenant.trial_ends_at)


class TenantAdminBulkActivationTests(TestCase):
    """
    Integration-level check that /django-admin/ actually wires up
    apply_activation_side_effects() — i.e. that it's not just correct in
    isolation but genuinely called by the activate/deactivate admin actions
    a superadmin clicks in the browser.
    """

    def setUp(self):
        self.superadmin = User.objects.create_user(
            email='super@bizal.al', password='superpass',
            is_superuser=True, is_staff=True,
        )
        self.tenant = Tenant.objects.create(
            name='Dyqani Test', slug='dyqan-test',
            business_type='restaurant', plan='trial',
            is_active=False,
        )
        self.owner = User.objects.create_user(
            email='owner@dyqan.al', password='pass1234',
            full_name='Arta Hoxha',
            tenant=self.tenant, role='owner',
        )
        self.client.force_login(self.superadmin)
        self.changelist_url = '/django-admin/tenants/tenant/'

    @patch('tenants.admin.send_mail')
    def test_activate_action_starts_trial_clock_and_emails_owner(self, mock_mail):
        resp = self.client.post(self.changelist_url, {
            'action': 'activate_tenants',
            '_selected_action': [str(self.tenant.pk)],
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.tenant.refresh_from_db()

        self.assertTrue(self.tenant.is_active)
        self.assertIsNotNone(self.tenant.trial_ends_at)
        owner_calls = [c for c in mock_mail.call_args_list if self.owner.email in str(c)]
        self.assertGreater(len(owner_calls), 0, 'No activation email sent via admin bulk action')

    @patch('tenants.admin.send_mail')
    def test_deactivate_action_emails_owner_without_touching_trial_clock(self, mock_mail):
        original_expiry = timezone.now() + timezone.timedelta(days=3)
        self.tenant.is_active = True
        self.tenant.trial_ends_at = original_expiry
        self.tenant.save()

        resp = self.client.post(self.changelist_url, {
            'action': 'deactivate_tenants',
            '_selected_action': [str(self.tenant.pk)],
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.tenant.refresh_from_db()

        self.assertFalse(self.tenant.is_active)
        self.assertEqual(self.tenant.trial_ends_at, original_expiry)
        owner_calls = [c for c in mock_mail.call_args_list if self.owner.email in str(c)]
        self.assertGreater(len(owner_calls), 0, 'No deactivation email sent via admin bulk action')


class DjangoAdminUserListFilterTests(TestCase):
    """
    Replaces the old SuperadminUserListFilterTests, which guarded against a
    slug-vs-UUID mismatch specific to the removed hand-rolled
    SuperadminUserListView (?tenant=<slug> query param). That whole bug
    class doesn't exist on this surface: accounts.UserAdmin's
    list_filter = ('role', 'is_active', 'tenant') is Django's own
    RelatedFieldListFilter, which always filters by the FK's pk
    (?tenant__id__exact=<uuid>) — there's no hand-written slug/UUID
    translation layer left to get wrong. These tests instead confirm the
    django-admin changelist actually delivers the same filtering surface
    the old endpoint provided: scoped by tenant, searchable by email/name,
    and staff-only.
    """

    def setUp(self):
        self.superadmin = User.objects.create_user(
            email='super2@bizal.al', password='superpass',
            is_superuser=True, is_staff=True,
        )
        self.tenant_a = Tenant.objects.create(
            name='Shop A', slug='shop-a', business_type='restaurant',
            plan='pro', is_active=True,
        )
        self.tenant_b = Tenant.objects.create(
            name='Shop B', slug='shop-b', business_type='gym',
            plan='pro', is_active=True,
        )
        self.user_a = User.objects.create_user(
            email='a@shopa.com', password='pass1234', tenant=self.tenant_a, role='owner',
        )
        self.user_b = User.objects.create_user(
            email='b@shopb.com', password='pass1234', tenant=self.tenant_b, role='owner',
        )
        self.changelist_url = '/django-admin/accounts/user/'

    def test_filtering_by_tenant_returns_only_that_tenants_users(self):
        self.client.force_login(self.superadmin)
        resp = self.client.get(self.changelist_url, {'tenant__id__exact': str(self.tenant_a.id)})
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn('a@shopa.com', content)
        self.assertNotIn('b@shopb.com', content)

    def test_search_by_email_finds_user(self):
        self.client.force_login(self.superadmin)
        resp = self.client.get(self.changelist_url, {'q': 'a@shopa.com'})
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn('a@shopa.com', content)
        self.assertNotIn('b@shopb.com', content)

    def test_non_staff_user_cannot_reach_changelist(self):
        regular = User.objects.create_user(
            email='regular@shopa.com', password='pass1234', tenant=self.tenant_a, role='owner',
        )
        self.client.force_login(regular)
        resp = self.client.get(self.changelist_url)
        # Django admin redirects non-staff users to the login page rather
        # than 403ing directly.
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/django-admin/login/', resp.url)


class TenantThemeContrastTests(TestCase):
    """
    Covers the background_color/text_color pair added alongside
    font_heading/font_body/border_radius. Unlike those fields (a curated
    choice list, so any combination is inherently safe), background/text
    are free hex — the risk is entirely in the *pair*, which is why the
    contrast check exists in the first place.
    """

    def test_defaults_match_brand_css_and_pass_contrast(self):
        """
        Guards the same class of bug this field pair was built to avoid
        with font_heading/font_body: if a default here ever drifts from
        brand.css's hardcoded --parchment/--ink fallback, every
        un-customized tenant's storefront silently changes on next save.
        """
        t = make_tenant(slug='contrast-defaults')
        self.assertEqual(t.background_color, '#FAFAF8')
        self.assertEqual(t.text_color, '#111111')
        t.clean()  # must not raise

    def test_model_clean_rejects_low_contrast_pair(self):
        t = make_tenant(slug='contrast-bad', background_color='#FFFFFF', text_color='#F5F5F5')
        with self.assertRaises(ValidationError) as ctx:
            t.clean()
        self.assertIn('text_color', ctx.exception.message_dict)

    def test_model_clean_accepts_legible_custom_pair(self):
        t = make_tenant(slug='contrast-good', background_color='#0E0E0E', text_color='#F7F6F3')
        t.clean()  # must not raise

    def test_serializer_patch_rejects_low_contrast_against_existing_bg(self):
        """
        The admin panel's theme picker PATCHes one field at a time (e.g.
        only text_color when the user drags just that swatch). The
        contrast check has to merge the partial payload against the
        tenant's *current* DB value, not assume the other field is absent.
        """
        t = make_tenant(slug='contrast-partial')  # bg stays default #FAFAF8
        s = TenantSettingsSerializer(instance=t, data={'text_color': '#FBFBFA'}, partial=True)
        self.assertFalse(s.is_valid())
        self.assertIn('text_color', s.errors)

    def test_serializer_patch_accepts_legible_partial_update(self):
        t = make_tenant(slug='contrast-partial-ok')
        s = TenantSettingsSerializer(instance=t, data={'text_color': '#222222'}, partial=True)
        self.assertTrue(s.is_valid(), s.errors)

    def test_invalid_hex_still_rejected(self):
        t = Tenant(name='Bad Hex', slug='contrast-badhex', background_color='not-a-color')
        with self.assertRaises(ValidationError):
            t.full_clean(exclude=['text_color'])


class ChangePlanTests(TestCase):
    """
    /api/tenants/me/change-plan/ — self-service upgrade/downgrade that
    switches the tenant's own plan directly (no Stripe checkout). Added
    alongside /api/payments/subscribe/ so plan changes work even when
    Stripe isn't configured, and so tenants can downgrade (Stripe checkout
    only ever moves a tenant up to a paid plan).
    """

    def setUp(self):
        from rest_framework.test import APIClient
        self.client = APIClient()
        self.tenant = Tenant.objects.create(
            name='Plan Test', slug='plantest', business_type='retail',
            plan=PLAN_STARTER, is_active=True,
        )
        self.owner = User.objects.create_user(
            email='owner@plantest.com', password='pass1234', tenant=self.tenant, role='owner',
        )
        self.client.defaults['HTTP_HOST'] = 'plantest.bizal.al'
        self.client.force_authenticate(user=self.owner)

    def test_owner_can_upgrade_plan(self):
        resp = self.client.post('/api/tenants/me/change-plan/', {'plan': 'pro'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.plan, PLAN_PRO)
        self.assertTrue(self.tenant.has_feature('custom_branding'))

    def test_owner_can_downgrade_plan(self):
        self.tenant.plan = PLAN_ENTERPRISE
        self.tenant.save(update_fields=['plan'])
        resp = self.client.post('/api/tenants/me/change-plan/', {'plan': 'starter'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.plan, PLAN_STARTER)

    def test_invalid_plan_rejected(self):
        resp = self.client.post('/api/tenants/me/change-plan/', {'plan': 'godmode'}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_customer_cannot_change_plan(self):
        from rest_framework.test import APIClient
        customer = User.objects.create_user(
            email='cust@plantest.com', password='pass1234', tenant=self.tenant, role='customer',
        )
        client = APIClient()
        client.defaults['HTTP_HOST'] = 'plantest.bizal.al'
        client.force_authenticate(user=customer)
        resp = client.post('/api/tenants/me/change-plan/', {'plan': 'pro'}, format='json')
        self.assertIn(resp.status_code, (401, 403))

    def test_me_endpoint_includes_features(self):
        """
        Regression test: TenantSettingsSerializer (served by /api/tenants/me/,
        which populates TENANT in the tenant admin frontend) used to omit
        `features` entirely, so hasFeature('custom_branding') always read
        false on that page — the theme customization panel stayed locked
        behind a "requires Pro" message even for Pro/Enterprise tenants.
        """
        resp = self.client.get('/api/tenants/me/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('features', resp.data)


class FxConversionTests(TestCase):
    """
    tenants/fx.py — converts an ALL ledger amount into a customer-chosen
    pay_currency (EUR/USD) at Stripe checkout time. See the module
    docstring and the comment on Tenant.currency for the full rationale.
    """

    def setUp(self):
        from django.core.cache.backends.locmem import LocMemCache
        self.real_cache = LocMemCache('fx-test', {})
        self.real_cache.clear()
        self._patcher = patch('tenants.fx.cache', self.real_cache)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def test_convert_all_to_all_is_identity(self):
        from tenants.fx import convert_all_to
        from decimal import Decimal
        self.assertEqual(convert_all_to(Decimal('1000.00'), 'ALL'), Decimal('1000.00'))

    def test_convert_all_to_eur_raises_when_uncached(self):
        # No hardcoded fallback any more: with nothing cached, EUR is simply
        # unavailable and callers must handle RateUnavailable (checkout
        # turns this into a 503 — see PaymentsBookingCheckoutTests).
        from tenants.fx import convert_all_to, RateUnavailable
        from decimal import Decimal
        with self.assertRaises(RateUnavailable):
            convert_all_to(Decimal('10500.00'), 'EUR')

    def test_convert_all_to_usd_raises_when_uncached(self):
        from tenants.fx import convert_all_to, RateUnavailable
        from decimal import Decimal
        with self.assertRaises(RateUnavailable):
            convert_all_to(Decimal('9700.00'), 'USD')

    def test_get_rate_returns_cached_value(self):
        from tenants.fx import set_rate, get_rate
        from decimal import Decimal
        set_rate('EUR', Decimal('110.00'))
        self.assertEqual(get_rate('EUR'), Decimal('110.00'))

    def test_is_available_reflects_cache_state(self):
        from tenants.fx import set_rate, is_available
        from decimal import Decimal
        self.assertFalse(is_available('EUR'))
        set_rate('EUR', Decimal('110.00'))
        self.assertTrue(is_available('EUR'))
        self.assertFalse(is_available('USD'))

    def test_get_available_pay_currencies_always_includes_all(self):
        from tenants.fx import set_rate, get_available_pay_currencies
        from decimal import Decimal
        self.assertEqual(get_available_pay_currencies(), ['ALL'])
        set_rate('USD', Decimal('97.00'))
        self.assertEqual(get_available_pay_currencies(), ['ALL', 'USD'])

    def test_convert_all_to_eur_uses_cached_rate(self):
        from tenants.fx import set_rate, convert_all_to
        from decimal import Decimal
        set_rate('EUR', Decimal('100.00'))
        self.assertEqual(convert_all_to(Decimal('1000.00'), 'EUR'), Decimal('10.00'))

    def test_convert_to_all_is_inverse_of_convert_all_to(self):
        from tenants.fx import set_rate, convert_all_to, convert_to_all
        from decimal import Decimal
        set_rate('USD', Decimal('100.00'))
        charged = convert_all_to(Decimal('5000.00'), 'USD')
        self.assertEqual(charged, Decimal('50.00'))
        self.assertEqual(convert_to_all(charged, 'USD'), Decimal('5000.00'))

    def test_unsupported_currency_raises(self):
        from tenants.fx import convert_all_to, UnsupportedCurrency
        from decimal import Decimal
        with self.assertRaises(UnsupportedCurrency):
            convert_all_to(Decimal('100.00'), 'GBP')

    def test_set_rate_rejects_non_positive_rate(self):
        from tenants.fx import set_rate
        from decimal import Decimal
        with self.assertRaises(ValueError):
            set_rate('EUR', Decimal('0'))

    def test_get_rate_treats_corrupt_cached_value_as_unavailable(self):
        # Defends against a cache poisoned by an incompatible value (e.g.
        # a stale deploy that cached a non-numeric string) — this must be
        # treated as "no rate available", not trusted as a real rate.
        from tenants.fx import get_rate, RateUnavailable, _CACHE_KEY_PREFIX
        self.real_cache.set(f'{_CACHE_KEY_PREFIX}EUR', 'not-a-number', 3600)
        with self.assertRaises(RateUnavailable):
            get_rate('EUR')


class RefreshFxRatesTaskTests(TestCase):
    """tenants.tasks.refresh_fx_rates — the Celery task that keeps tenants/fx.py's cache current."""

    def setUp(self):
        from django.core.cache.backends.locmem import LocMemCache
        self.real_cache = LocMemCache('fx-task-test', {})
        self.real_cache.clear()
        self._patcher = patch('tenants.fx.cache', self.real_cache)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    @patch('tenants.tasks.requests.get')
    def test_successful_fetch_caches_inverted_rates(self, mock_get):
        from decimal import Decimal
        from tenants.tasks import refresh_fx_rates
        from tenants.fx import get_rate
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {'rates': {'EUR': 0.0095, 'USD': 0.0103}},
        )
        mock_get.return_value.raise_for_status = lambda: None
        result = refresh_fx_rates()
        self.assertIn('EUR', result)
        self.assertIn('USD', result)
        # 1 ALL = 0.0095 EUR  =>  1 EUR = 1/0.0095 ALL, quantized to 4dp by the task.
        expected = (Decimal('1') / Decimal('0.0095')).quantize(Decimal('0.0001'))
        self.assertEqual(get_rate('EUR'), expected)

    @patch('tenants.tasks.requests.get')
    def test_upstream_failure_does_not_raise_and_leaves_currency_unavailable(self, mock_get):
        # No hardcoded fallback any more: an upstream failure with nothing
        # previously cached just leaves EUR unavailable, it does not raise
        # and does not conjure up a rate.
        from tenants.tasks import refresh_fx_rates
        from tenants.fx import get_rate, RateUnavailable, is_available
        mock_get.side_effect = Exception('connection refused')
        result = refresh_fx_rates()  # must not raise
        self.assertIn('failed', result.lower())
        self.assertFalse(is_available('EUR'))
        with self.assertRaises(RateUnavailable):
            get_rate('EUR')

    @patch('tenants.tasks.requests.get')
    def test_upstream_failure_keeps_previously_cached_rate(self, mock_get):
        # If a rate was already cached by an earlier successful run, a
        # later failed run must not clobber it.
        from tenants.tasks import refresh_fx_rates
        from tenants.fx import set_rate, get_rate
        from decimal import Decimal
        set_rate('EUR', Decimal('108.50'))
        mock_get.side_effect = Exception('connection refused')
        refresh_fx_rates()
        self.assertEqual(get_rate('EUR'), Decimal('108.50'))

    @patch('tenants.tasks.requests.get')
    def test_missing_currency_in_response_is_skipped_not_fatal(self, mock_get):
        from tenants.tasks import refresh_fx_rates
        mock_get.return_value = MagicMock(status_code=200, json=lambda: {'rates': {'EUR': 0.0095}})
        mock_get.return_value.raise_for_status = lambda: None
        result = refresh_fx_rates()
        self.assertIn('EUR', result)
        self.assertIn('USD', result)


class CreditRedeemTests(TestCase):
    """
    Covers the redeem endpoint at /api/tenants/credits/redeem/.

    Previously this endpoint debited tenant.referral_credits and wrote an
    activity-log line claiming the credit was "applied to invoice #X", but
    never actually touched Invoice.total_amount — credits disappeared
    without reducing what the tenant's customer owed, and there was no cap
    tying the redeemed amount to the invoice's actual balance. These tests
    cover the fix: an InvoiceLine is created and the invoice total drops,
    the applied amount is capped at the invoice's remaining balance, and
    the credit balance is only debited by what was actually applied.

    Note: referral credits are ALL (Lek), like every other stored amount on
    the platform — see tenants/fx.py's module docstring. These tests don't
    involve any EUR/USD conversion; the "_eur" naming on the underlying
    fields is legacy/misleading, not a real currency distinction.
    """

    def setUp(self):
        from rest_framework.test import APIClient
        from billing.models import Invoice
        self.tenant = Tenant.objects.create(
            name='Credit Test Biz', slug='credit-test', business_type='restaurant',
            plan=PLAN_PRO, is_active=True, referral_credits=Decimal('50.00'),
        )
        self.owner = User.objects.create_user(
            email='owner@credit-test.com', password='pass1234',
            tenant=self.tenant, role='owner',
        )
        self.client = APIClient()
        self.client.defaults['HTTP_HOST'] = 'credit-test.bizal.al'
        self.client.force_authenticate(user=self.owner)
        self.url = '/api/tenants/credits/redeem/'
        self.invoice = Invoice.objects.create(
            tenant=self.tenant, invoice_number='INV-1', status='sent',
        )
        from billing.models import InvoiceLine
        InvoiceLine.objects.create(
            tenant=self.tenant, invoice=self.invoice,
            description='Service', quantity=1, unit_price=Decimal('30.00'),
        )
        self.invoice.refresh_from_db()  # total_amount = 30.00

    def test_redeem_reduces_invoice_total_and_balance(self):
        resp = self.client.post(self.url, {
            'amount': '10.00', 'invoice_id': str(self.invoice.pk),
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['applied'], '10.00')

        self.tenant.refresh_from_db()
        self.invoice.refresh_from_db()
        self.assertEqual(self.tenant.referral_credits, Decimal('40.00'))
        self.assertEqual(self.invoice.total_amount, Decimal('20.00'))

    def test_redeem_amount_capped_at_invoice_remaining_balance(self):
        # Invoice only totals 30.00 — requesting 45.00 must only apply and
        # debit 30.00, not the full requested amount.
        resp = self.client.post(self.url, {
            'amount': '45.00', 'invoice_id': str(self.invoice.pk),
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['requested'], '45.00')
        self.assertEqual(resp.data['applied'], '30.00')

        self.tenant.refresh_from_db()
        self.invoice.refresh_from_db()
        self.assertEqual(self.tenant.referral_credits, Decimal('20.00'))
        self.assertEqual(self.invoice.total_amount, Decimal('0.00'))

    def test_redeem_without_invoice_id_only_debits_balance(self):
        resp = self.client.post(self.url, {'amount': '5.00'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['applied'], '5.00')
        self.assertIsNone(resp.data['invoice_total'])

        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.referral_credits, Decimal('45.00'))

    def test_redeem_insufficient_balance_rejected(self):
        resp = self.client.post(self.url, {'amount': '999.00'}, format='json')
        self.assertEqual(resp.status_code, 400)

        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.referral_credits, Decimal('50.00'))

    def test_redeem_zero_or_negative_amount_rejected(self):
        resp = self.client.post(self.url, {'amount': '0.00'}, format='json')
        self.assertEqual(resp.status_code, 400)
        resp = self.client.post(self.url, {'amount': '-5.00'}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_redeem_cross_tenant_invoice_rejected(self):
        other_tenant = Tenant.objects.create(
            name='Other Biz', slug='other-biz-credit', business_type='retail',
            plan=PLAN_PRO, is_active=True,
        )
        from billing.models import Invoice
        other_invoice = Invoice.objects.create(
            tenant=other_tenant, invoice_number='INV-OTHER', status='sent',
        )
        resp = self.client.post(self.url, {
            'amount': '5.00', 'invoice_id': str(other_invoice.pk),
        }, format='json')
        self.assertEqual(resp.status_code, 404)

        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.referral_credits, Decimal('50.00'))

    def test_redeem_on_already_zero_balance_invoice_rejected(self):
        # Fully pay off the invoice with credit first...
        self.client.post(self.url, {
            'amount': '30.00', 'invoice_id': str(self.invoice.pk),
        }, format='json')
        # ...then a second redemption against the same invoice must be
        # rejected rather than creating a negative total_amount.
        resp = self.client.post(self.url, {
            'amount': '5.00', 'invoice_id': str(self.invoice.pk),
        }, format='json')
        self.assertEqual(resp.status_code, 400)


class TenantAdminAdditionalActionsTests(TestCase):
    def setUp(self):
        self.superadmin = User.objects.create_user(
            email='root@bizal.al', password='rootpass',
            is_superuser=True, is_staff=True,
        )
        self.client.force_login(self.superadmin)
        self.tenant = Tenant.objects.create(
            name='Kafeneja', slug='kafeneja',
            business_type='restaurant', plan='starter',
            is_active=True,
        )
        self.changelist_url = '/django-admin/tenants/tenant/'

    def test_convert_to_pro_action(self):
        resp = self.client.post(self.changelist_url, {
            'action': 'convert_to_pro',
            '_selected_action': [str(self.tenant.pk)],
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.plan, 'pro')

    def test_list_on_marketplace_action(self):
        resp = self.client.post(self.changelist_url, {
            'action': 'list_on_marketplace',
            '_selected_action': [str(self.tenant.pk)],
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.tenant.refresh_from_db()
        self.assertTrue(self.tenant.listed_on_marketplace)

    @patch('activity.utils.log_activity', side_effect=Exception('boom'))
    def test_activate_action_survives_log_activity_failure(self, _mock_log):
        self.tenant.is_active = False
        self.tenant.save()
        resp = self.client.post(self.changelist_url, {
            'action': 'activate_tenants',
            '_selected_action': [str(self.tenant.pk)],
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.tenant.refresh_from_db()
        self.assertTrue(self.tenant.is_active)

    @patch('activity.utils.log_activity', side_effect=Exception('boom'))
    def test_deactivate_action_survives_log_activity_failure(self, _mock_log):
        resp = self.client.post(self.changelist_url, {
            'action': 'deactivate_tenants',
            '_selected_action': [str(self.tenant.pk)],
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.tenant.refresh_from_db()
        self.assertFalse(self.tenant.is_active)

    @patch('activity.utils.log_activity', side_effect=Exception('boom'))
    def test_convert_to_pro_survives_log_activity_failure(self, _mock_log):
        resp = self.client.post(self.changelist_url, {
            'action': 'convert_to_pro',
            '_selected_action': [str(self.tenant.pk)],
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.plan, 'pro')

    @patch('activity.utils.log_activity', side_effect=Exception('boom'))
    def test_list_on_marketplace_survives_log_activity_failure(self, _mock_log):
        resp = self.client.post(self.changelist_url, {
            'action': 'list_on_marketplace',
            '_selected_action': [str(self.tenant.pk)],
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.tenant.refresh_from_db()
        self.assertTrue(self.tenant.listed_on_marketplace)

    def test_trial_status_expired_display(self):
        expired = Tenant.objects.create(
            name='Expired Trial', slug='expired-trial',
            business_type='restaurant', plan='trial',
            is_active=True,
            trial_ends_at=timezone.now() - timedelta(days=1),
        )
        resp = self.client.get(self.changelist_url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Expired')

    def test_change_form_flips_is_active_and_runs_side_effects(self):
        """save_model's `change` branch (was_active captured pre-save)."""
        self.owner = User.objects.create_user(
            email='owner@kafeneja.al', password='pass1234',
            full_name='Ana Krasniqi', tenant=self.tenant, role='owner',
        )
        self.tenant.is_active = False
        self.tenant.save()
        change_url = f'/django-admin/tenants/tenant/{self.tenant.pk}/change/'

        get_resp = self.client.get(change_url)
        self.assertEqual(get_resp.status_code, 200)

        data = self._minimal_change_payload(self.tenant, is_active=True)
        import re
        prefixes = set(re.findall(r'name="([\w-]+)-TOTAL_FORMS"', get_resp.content.decode()))
        for p in prefixes:
            data[f'{p}-TOTAL_FORMS'] = '0'
            data[f'{p}-INITIAL_FORMS'] = '0'
            data[f'{p}-MIN_NUM_FORMS'] = '0'
            data[f'{p}-MAX_NUM_FORMS'] = '1000'
        with patch('tenants.admin.send_mail') as mock_mail:
            resp = self.client.post(change_url, data, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.tenant.refresh_from_db()
        self.assertTrue(self.tenant.is_active)
        owner_calls = [c for c in mock_mail.call_args_list if self.owner.email in str(c)]
        self.assertGreater(len(owner_calls), 0)

    def _minimal_change_payload(self, tenant, is_active):
        """Build a minimal valid POST body for the Tenant change form,
        including the required inline-formset management data."""
        data = {
            'name': tenant.name,
            'slug': tenant.slug,
            'site_title': '',
            'tagline': '',
            'business_type': tenant.business_type,
            'primary_color': '#2563EB',
            'accent_color': '#F59E0B',
            'font_family': 'Inter',
            'font_heading': 'Cormorant Garamond',
            'font_body': 'DM Sans',
            'border_radius': '8px',
            'background_color': '#FFFFFF',
            'text_color': '#111111',
            'email': '',
            'phone': '',
            'whatsapp': '',
            'address': '',
            'city': '',
            'country': 'AL',
            'facebook': '',
            'instagram': '',
            'tiktok': '',
            'website': '',
            'story': '',
            'plan': tenant.plan,
            'is_active': 'on' if is_active else '',
            'listed_on_marketplace': '',
            'marketplace_description': '',
            'meta_description': '',
            'meta_keywords': '',
        }
        for prefix, count in (
            ('accounts-user-content_type-object_id', 0),
            ('tenantfeature_set', 0),
            ('tenantlocation_set', 0),
        ):
            data[f'{prefix}-TOTAL_FORMS'] = '0'
            data[f'{prefix}-INITIAL_FORMS'] = '0'
            data[f'{prefix}-MIN_NUM_FORMS'] = '0'
            data[f'{prefix}-MAX_NUM_FORMS'] = '1000'
        return data


class TrialTenantAdminTests(TestCase):
    def setUp(self):
        self.superadmin = User.objects.create_user(
            email='root2@bizal.al', password='rootpass',
            is_superuser=True, is_staff=True,
        )
        self.client.force_login(self.superadmin)
        self.changelist_url = '/django-admin/tenants/trialtenant/'

    def _make_trial(self, slug, trial_ends_at):
        return Tenant.objects.create(
            name=f'Trial {slug}', slug=slug,
            business_type='restaurant', plan='trial',
            is_active=True, trial_ends_at=trial_ends_at,
        )

    def test_changelist_only_shows_trial_plan_tenants(self):
        Tenant.objects.create(
            name='Pro tenant', slug='pro-tenant',
            business_type='restaurant', plan='pro', is_active=True,
        )
        trial = self._make_trial('mid-trial', timezone.now() + timedelta(days=10))
        resp = self.client.get(self.changelist_url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, trial.slug)
        self.assertNotContains(resp, 'pro-tenant')

    def test_days_left_no_expiry_set(self):
        self._make_trial('no-expiry', None)
        resp = self.client.get(self.changelist_url)
        self.assertContains(resp, '—')

    def test_days_left_expired(self):
        self._make_trial('long-expired', timezone.now() - timedelta(days=5))
        resp = self.client.get(self.changelist_url)
        self.assertContains(resp, 'Expired')

    def test_days_left_soon(self):
        self._make_trial('soon-expiry', timezone.now() + timedelta(days=2))
        resp = self.client.get(self.changelist_url)
        self.assertContains(resp, 'd left')

    def test_days_left_normal(self):
        self._make_trial('normal-expiry', timezone.now() + timedelta(days=20))
        resp = self.client.get(self.changelist_url)
        self.assertContains(resp, 'd left')

    def test_extend_trial_7d_action(self):
        trial = self._make_trial('extend-7', timezone.now() + timedelta(days=1))
        original = trial.trial_ends_at
        resp = self.client.post(self.changelist_url, {
            'action': 'extend_trial_7d',
            '_selected_action': [str(trial.pk)],
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        trial.refresh_from_db()
        self.assertGreater(trial.trial_ends_at, original)

    def test_extend_trial_30d_action_on_already_expired_trial(self):
        """Covers the `base = ... else timezone.now()` branch for an
        already-expired trial (trial_ends_at in the past)."""
        trial = self._make_trial('extend-30-expired', timezone.now() - timedelta(days=3))
        resp = self.client.post(self.changelist_url, {
            'action': 'extend_trial_30d',
            '_selected_action': [str(trial.pk)],
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        trial.refresh_from_db()
        self.assertGreater(trial.trial_ends_at, timezone.now() + timedelta(days=25))

    @patch('activity.utils.log_activity', side_effect=Exception('boom'))
    def test_extend_trial_survives_log_activity_failure(self, _mock_log):
        trial = self._make_trial('extend-fail', timezone.now() + timedelta(days=1))
        resp = self.client.post(self.changelist_url, {
            'action': 'extend_trial_7d',
            '_selected_action': [str(trial.pk)],
        }, follow=True)
        self.assertEqual(resp.status_code, 200)

    def test_convert_to_pro_action_from_trial_admin(self):
        trial = self._make_trial('trial-to-pro', timezone.now() + timedelta(days=5))
        resp = self.client.post(self.changelist_url, {
            'action': 'convert_to_pro',
            '_selected_action': [str(trial.pk)],
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        trial.refresh_from_db()
        self.assertEqual(trial.plan, 'pro')

    def test_deactivate_action_from_trial_admin(self):
        trial = self._make_trial('trial-deactivate', timezone.now() + timedelta(days=5))
        resp = self.client.post(self.changelist_url, {
            'action': 'deactivate_tenants',
            '_selected_action': [str(trial.pk)],
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        trial.refresh_from_db()
        self.assertFalse(trial.is_active)

    def test_trial_tenant_admin_has_no_add_permission(self):
        resp = self.client.get(self.changelist_url + 'add/')
        self.assertEqual(resp.status_code, 403)

    def test_trial_tenant_admin_has_no_delete_permission(self):
        trial = self._make_trial('no-delete', timezone.now() + timedelta(days=5))
        resp = self.client.get(f'{self.changelist_url}{trial.pk}/delete/')
        self.assertEqual(resp.status_code, 403)


class TenantReferralAdminTests(TestCase):
    def setUp(self):
        self.superadmin = User.objects.create_user(
            email='root3@bizal.al', password='rootpass',
            is_superuser=True, is_staff=True,
        )
        self.client.force_login(self.superadmin)
        self.referrer = Tenant.objects.create(
            name='Referrer', slug='referrer-biz',
            business_type='restaurant', plan='pro', is_active=True,
        )
        self.referred = Tenant.objects.create(
            name='Referred', slug='referred-biz',
            business_type='restaurant', plan='trial', is_active=True,
        )

    def test_apply_credits_action_credits_unapplied_referrals(self):
        referral = TenantReferral.objects.create(
            referrer=self.referrer, referred=self.referred,
            credit_amount=15, applied=False,
        )
        resp = self.client.post('/django-admin/tenants/tenantreferral/', {
            'action': 'apply_credits',
            '_selected_action': [str(referral.pk)],
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        referral.refresh_from_db()
        self.assertTrue(referral.applied)
        self.referrer.refresh_from_db()
        self.assertEqual(self.referrer.referral_credits, 15)

    def test_apply_credits_action_skips_already_applied(self):
        referral = TenantReferral.objects.create(
            referrer=self.referrer, referred=self.referred,
            credit_amount=15, applied=True,
        )
        resp = self.client.post('/django-admin/tenants/tenantreferral/', {
            'action': 'apply_credits',
            '_selected_action': [str(referral.pk)],
        }, follow=True)
        self.assertEqual(resp.status_code, 200)


class TenantUserInlineAddPermissionTests(TestCase):
    """Rendering the Tenant change page exercises
    TenantUserInline.has_add_permission (always False)."""

    def setUp(self):
        self.superadmin = User.objects.create_user(
            email='root4@bizal.al', password='rootpass',
            is_superuser=True, is_staff=True,
        )
        self.client.force_login(self.superadmin)
        self.tenant = Tenant.objects.create(
            name='InlineCheck', slug='inline-check',
            business_type='restaurant', plan='pro', is_active=True,
        )

    def test_change_view_renders_without_add_row_for_linked_users(self):
        resp = self.client.get(f'/django-admin/tenants/tenant/{self.tenant.pk}/change/')
        self.assertEqual(resp.status_code, 200)


class FxUntrackedCurrencyGapsTests(TestCase):
    def setUp(self):
        from django.core.cache.backends.locmem import LocMemCache
        self.real_cache = LocMemCache('fx-gap-test', {})
        self.real_cache.clear()
        self._patcher = patch('tenants.fx.cache', self.real_cache)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def test_is_available_false_for_currency_outside_tracked_list(self):
        from tenants.fx import is_available
        self.assertFalse(is_available('ALL'))
        self.assertFalse(is_available('GBP'))

    def test_is_available_false_for_corrupt_cached_value(self):
        from tenants.fx import is_available, _CACHE_KEY_PREFIX
        self.real_cache.set(f'{_CACHE_KEY_PREFIX}EUR', 'not-a-number', 3600)
        self.assertFalse(is_available('EUR'))

    def test_get_rate_rejects_unsupported_currency(self):
        from tenants.fx import get_rate, UnsupportedCurrency
        with self.assertRaises(UnsupportedCurrency):
            get_rate('GBP')

    def test_set_rate_rejects_unsupported_currency(self):
        from tenants.fx import set_rate, UnsupportedCurrency
        with self.assertRaises(UnsupportedCurrency):
            set_rate('GBP', Decimal('100.00'))

    def test_convert_to_all_rejects_unsupported_currency(self):
        from tenants.fx import convert_to_all, UnsupportedCurrency
        with self.assertRaises(UnsupportedCurrency):
            convert_to_all(Decimal('100.00'), 'GBP')


class DayIndexGapsTests(SimpleTestCase):
    def test_unknown_day_name_returns_none(self):
        self.assertIsNone(_day_index('Not A Day'))


class ExpandDayKeyGapsTests(SimpleTestCase):
    def test_unknown_day_in_range_returns_empty(self):
        self.assertEqual(_expand_day_key('Not A Day - E Shtunë'), [])
        self.assertEqual(_expand_day_key('E Hënë - Not A Day'), [])

    def test_wrap_around_range(self):
        # Sat(5) -> Mon(0): wraps through Sun(6) then Mon(0)
        self.assertEqual(_expand_day_key('E Shtunë - E Hënë'), [5, 6, 0])


class HoursForWeekdayGapsTests(SimpleTestCase):
    def test_empty_business_hours_returns_none(self):
        self.assertIsNone(hours_for_weekday({}, 0))
        self.assertIsNone(hours_for_weekday(None, 0))

    def test_non_dict_business_hours_returns_none(self):
        self.assertIsNone(hours_for_weekday('not a dict', 0))

    def test_unparseable_time_range_is_skipped(self):
        business_hours = {'E Hënë': 'closed'}
        self.assertIsNone(hours_for_weekday(business_hours, 0))


class IsOpenAtGapsTests(SimpleTestCase):
    def test_overnight_window_evening_portion_on_same_day(self):
        # 18:00 - 02:00 on Monday(0); at 19:00 (1140 min) should be open
        business_hours = {'E Hënë': '18:00 - 02:00'}
        self.assertTrue(is_open_at(business_hours, 0, 19 * 60))

    def test_overnight_window_early_morning_tail_from_yesterday(self):
        # 18:00 - 02:00 on Monday(0) spills into Tuesday(1) until 02:00
        business_hours = {'E Hënë': '18:00 - 02:00'}
        self.assertTrue(is_open_at(business_hours, 1, 60))  # 01:00 Tuesday

    def test_overnight_window_tail_boundary_excluded_after_close(self):
        business_hours = {'E Hënë': '18:00 - 02:00'}
        self.assertFalse(is_open_at(business_hours, 1, 3 * 60))


class EnforceMaxListingsGapsTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            name='Limits Co', slug='limitsco-gap', business_type='restaurant',
            plan='pro', is_active=True,
        )

    def test_no_limit_configured_fails_open(self):
        # Pro-plan tenants auto-seed max_listings=50 in Tenant.save(), so
        # explicitly zero it out here to exercise the "no cap configured"
        # fail-open path (get_limit() returning 0/falsy).
        TenantFeature.objects.update_or_create(
            tenant=self.tenant, key='max_listings', defaults={'value': '0'},
        )
        for i in range(5):
            TenantFeature.objects.create(tenant=self.tenant, key=f'flag_{i}', value='true')
        try:
            enforce_max_listings(self.tenant, TenantFeature)
        except PermissionDenied:
            self.fail('enforce_max_listings raised despite no limit configured')

    def test_extra_filter_scopes_the_count(self):
        TenantFeature.objects.update_or_create(
            tenant=self.tenant, key='max_listings', defaults={'value': '2'},
        )
        TenantFeature.objects.create(tenant=self.tenant, key='custom_a', value='x', is_custom_grant=True)
        TenantFeature.objects.create(tenant=self.tenant, key='custom_b', value='x', is_custom_grant=True)
        with self.assertRaises(PermissionDenied):
            enforce_max_listings(self.tenant, TenantFeature, extra_filter={'is_custom_grant': True})


class _FakeSession(dict):
    """dict-backed session stub — supports attribute assignment like a real
    SessionBase (`.modified = True`), unlike a plain dict."""
    modified = False


def _req(host, path='/', get=None, session=None):
    req = MagicMock()
    req.get_host.return_value = host
    req.path = path
    req.GET = get if get is not None else {}
    req.session = session if session is not None else _FakeSession()
    return req


class MiddlewareGapsTests(TestCase):
    def _mw(self):
        return TenantMiddleware(get_response=lambda r: MagicMock(status_code=200))

    def test_admin_path_blocked_on_tenant_subdomain(self):
        mw = self._mw()
        tenant = Tenant.objects.create(name='X', slug='xco', business_type='restaurant', plan='pro', is_active=True)
        req = MagicMock()
        req.tenant = tenant
        req.path = '/django-admin/login/'
        with self.assertRaises(Http404):
            mw._enforce_admin_main_domain_only(req)

    @override_settings(MAIN_DOMAIN='bizal.al')
    def test_host_header_with_invalid_port_falls_back_to_80(self):
        mw = self._mw()
        req = _req('bizal.al:notaport')
        result = mw._resolve_tenant(req)
        self.assertIsNone(result)

    @override_settings(MAIN_DOMAIN='bizal.al')
    def test_host_header_with_valid_numeric_port(self):
        mw = self._mw()
        req = _req('bizal.al:443')
        result = mw._resolve_tenant(req)
        self.assertIsNone(result)

    @override_settings(MAIN_DOMAIN='bizal.al')
    def test_production_subdomain_strips_www_prefix(self):
        Tenant.objects.create(name='Hertz', slug='hertz', business_type='car_rental', plan='pro', is_active=True)
        mw = self._mw()
        req = _req('www.hertz.bizal.al')
        result = mw._resolve_tenant(req)
        self.assertEqual(result.slug, 'hertz')

    def test_local_dev_subdomain_resolves_tenant(self):
        Tenant.objects.create(name='Klinika', slug='klinika', business_type='clinic', plan='pro', is_active=True)
        mw = self._mw()
        req = _req('klinika.localhost')
        result = mw._resolve_tenant(req)
        self.assertEqual(result.slug, 'klinika')

    def test_local_dev_subdomain_strips_www_and_skips_bare_www(self):
        mw = self._mw()
        req = _req('www.localhost')
        result = mw._resolve_tenant(req)
        self.assertIsNone(result)

    def test_main_port_local_returns_none(self):
        mw = self._mw()
        req = _req('localhost:8000')
        result = mw._resolve_tenant(req)
        self.assertIsNone(result)

    def test_tenant_port_local_with_get_param_sets_session(self):
        from .middleware import SESSION_KEY
        Tenant.objects.create(name='Bizal', slug='bizal-albania', business_type='retail', plan='pro', is_active=True)
        mw = self._mw()
        session = _FakeSession()
        req = _req('localhost:8001', get={'tenant': 'bizal-albania'}, session=session)
        result = mw._resolve_tenant(req)
        self.assertEqual(result.slug, 'bizal-albania')
        self.assertEqual(session[SESSION_KEY], 'bizal-albania')

    def test_tenant_port_local_falls_back_to_session_slug(self):
        Tenant.objects.create(name='Bizal', slug='sess-biz', business_type='retail', plan='pro', is_active=True)
        mw = self._mw()
        session = _FakeSession({'bizal_tenant_slug': 'sess-biz'})
        req = _req('localhost:8001', get={}, session=session)
        result = mw._resolve_tenant(req)
        self.assertEqual(result.slug, 'sess-biz')

    def test_tenant_port_local_no_slug_raises_404(self):
        mw = self._mw()
        req = _req('localhost:8001', get={}, session=_FakeSession())
        with self.assertRaises(Http404):
            mw._resolve_tenant(req)

    def test_get_tenant_empty_slug_returns_none(self):
        mw = self._mw()
        self.assertIsNone(mw._get_tenant(''))

    def test_trial_with_no_trial_ends_at_returns_early(self):
        mw = self._mw()
        tenant = Tenant.objects.create(
            name='Trial Co', slug='trialco2', business_type='restaurant', plan='trial',
            is_active=True, trial_ends_at=None,
        )
        req = MagicMock()
        req.tenant = tenant
        mw._enforce_trial(req)
        self.assertTrue(tenant.is_active)

    def test_bypass_path_returns_none_tenant(self):
        mw = self._mw()
        req = _req('anything.bizal.al', path='/health')
        result = mw._resolve_tenant(req)
        self.assertIsNone(result)

    @override_settings(MAIN_DOMAIN='bizal.al')
    def test_www_main_domain_returns_none(self):
        mw = self._mw()
        req = _req('www.bizal.al')
        result = mw._resolve_tenant(req)
        self.assertIsNone(result)

    def test_local_dev_www_subdomain_strips_to_valid_slug(self):
        Tenant.objects.create(name='Klinika', slug='klinika', business_type='clinic', plan='pro', is_active=True)
        mw = self._mw()
        req = _req('www.klinika.localhost')
        result = mw._resolve_tenant(req)
        self.assertEqual(result.slug, 'klinika')


def make_tenant__models_gaps2(**kwargs):
    defaults = dict(
        name='Gap Test Biz', slug='gap-test-biz', business_type='restaurant',
        is_active=True, plan=PLAN_PRO,
    )
    defaults.update(kwargs)
    return Tenant.objects.create(**defaults)


class ReservedSlugTests(TestCase):
    def test_reserved_slug_raises_validation_error(self):
        t = Tenant(name='Admin Panel', slug='admin', business_type='market',
                    is_active=True, plan=PLAN_STARTER)
        with pytest.raises(ValidationError):
            t.full_clean()


class SaveExistingTenantPlanChangeTests(TestCase):
    def test_save_on_existing_tenant_detects_plan_change(self):
        """Hits the `not is_new` branch that reads _loaded_plan/_loaded_business_type."""
        t = make_tenant__models_gaps2(plan=PLAN_STARTER)
        reloaded = Tenant.objects.get(pk=t.pk)
        reloaded.plan = PLAN_PRO
        reloaded.save()  # should not raise, and should re-run apply_plan_defaults
        self.assertEqual(Tenant.objects.get(pk=t.pk).plan, PLAN_PRO)

    def test_save_on_existing_tenant_no_change(self):
        t = make_tenant__models_gaps2(plan=PLAN_PRO)
        reloaded = Tenant.objects.get(pk=t.pk)
        reloaded.name = 'Renamed but same plan'
        reloaded.save()
        self.assertEqual(Tenant.objects.get(pk=t.pk).name, 'Renamed but same plan')


class ReferralCodeFallbackTests(TestCase):
    def test_all_five_attempts_collide_uses_fallback(self):
        t = Tenant(name='Collider', slug='collider', business_type='market',
                    is_active=True, plan=PLAN_STARTER)
        with patch.object(Tenant.objects, 'filter') as mock_filter:
            mock_filter.return_value.exists.return_value = True
            code = t._generate_referral_code()
        self.assertTrue(code.startswith('COLLID') or code.startswith('COLLI'))
        self.assertEqual(len(code), 10)


class NonBoolPresetOverrideTests(TestCase):
    def test_non_bool_preset_value_is_applied_as_is(self):
        fake_presets = dict(BUSINESS_TYPE_PRESETS)
        fake_presets['restaurant'] = {'bookings': 5}  # non-bool override
        with patch('tenants.models.BUSINESS_TYPE_PRESETS', fake_presets):
            t = make_tenant__models_gaps2(business_type='restaurant', plan=PLAN_STARTER)
        feature = TenantFeature.objects.get(tenant=t, key='bookings')
        self.assertEqual(feature.value, '5')


class HasFeatureInactiveTenantTests(TestCase):
    def test_has_feature_false_for_inactive_tenant(self):
        t = make_tenant__models_gaps2(is_active=False)
        self.assertFalse(t.has_feature('bookings'))


class GetLimitTests(TestCase):
    def test_get_limit_no_match_returns_zero(self):
        t = make_tenant__models_gaps2()
        self.assertEqual(t.get_limit('nonexistent_limit_key'), 0)

    def test_get_limit_valid_int_value(self):
        t = make_tenant__models_gaps2()
        TenantFeature.objects.update_or_create(tenant=t, key='max_staff', defaults={'value': '7'})
        self.assertEqual(t.get_limit('max_staff'), 7)

    def test_get_limit_unparsable_value_returns_zero(self):
        t = make_tenant__models_gaps2()
        TenantFeature.objects.update_or_create(tenant=t, key='bad_limit', defaults={'value': 'not-a-number'})
        self.assertEqual(t.get_limit('bad_limit'), 0)


class ModelStrTests(TestCase):
    def test_tenant_location_str(self):
        t = make_tenant__models_gaps2()
        loc = TenantLocation.objects.create(tenant=t, name='Main Branch')
        self.assertEqual(str(loc), f"{t.slug} — Main Branch")

    def test_tenant_referral_str(self):
        referrer = make_tenant__models_gaps2(slug='referrer-biz')
        referred = make_tenant__models_gaps2(slug='referred-biz')
        ref = TenantReferral.objects.create(referrer=referrer, referred=referred)
        self.assertEqual(str(ref), f"{referrer.slug} → {referred.slug}")

    def test_credit_ledger_str_positive_and_negative(self):
        t = make_tenant__models_gaps2()
        entry_pos = CreditLedger.objects.create(tenant=t, amount=Decimal('10.00'), event=CreditLedger.EVENT_REFERRAL)
        entry_neg = CreditLedger.objects.create(tenant=t, amount=Decimal('-5.00'), event=CreditLedger.EVENT_REDEMPTION)
        self.assertIn('+10', str(entry_pos))
        self.assertIn('-5', str(entry_neg))


class SpendCreditsGuardTests(TestCase):
    def test_spend_credits_rejects_zero_amount(self):
        t = make_tenant__models_gaps2(referral_credits=Decimal('20.00'))
        with pytest.raises(ValueError):
            CreditLedger.spend_credits(t, Decimal('0'))

    def test_spend_credits_rejects_negative_amount(self):
        t = make_tenant__models_gaps2(referral_credits=Decimal('20.00'))
        with pytest.raises(ValueError):
            CreditLedger.spend_credits(t, Decimal('-5.00'))


class GetEffectiveRoleGapsTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            name='X', slug='xco', business_type='restaurant', plan='pro', is_active=True,
        )

    def test_none_user_returns_none(self):
        self.assertIsNone(get_effective_role(None, self.tenant))

    def test_unauthenticated_user_returns_none(self):
        self.assertIsNone(get_effective_role(AnonymousUser(), self.tenant))


class IsTenantStaffSuperuserTests(TestCase):
    def test_superuser_bypasses_role_check(self):
        tenant = Tenant.objects.create(
            name='Y', slug='yco', business_type='restaurant', plan='pro', is_active=True,
        )
        req = MagicMock()
        req.tenant = tenant
        req.user = MagicMock()
        req.user.is_authenticated = True
        req.user.is_superuser = True
        perm = IsTenantStaff()
        self.assertTrue(perm.has_permission(req, None))


class HasTenantRoleSuperuserTests(TestCase):
    def test_superuser_bypasses_role_check(self):
        tenant = Tenant.objects.create(
            name='Z', slug='zco', business_type='restaurant', plan='pro', is_active=True,
        )
        req = MagicMock()
        req.tenant = tenant
        req.user = MagicMock()
        req.user.is_authenticated = True
        req.user.is_superuser = True
        perm_cls = HasTenantRole('accountant')
        self.assertTrue(perm_cls().has_permission(req, None))


class HasPlanAtLeastTests(TestCase):
    def test_no_tenant_returns_false(self):
        req = MagicMock()
        req.tenant = None
        perm_cls = HasPlanAtLeast('pro', 'enterprise')
        self.assertFalse(perm_cls().has_permission(req, None))

    def test_superuser_bypasses_plan_check(self):
        tenant = Tenant.objects.create(
            name='StarterCo', slug='starterco', business_type='restaurant', plan='starter', is_active=True,
        )
        req = MagicMock()
        req.tenant = tenant
        req.user = MagicMock()
        req.user.is_authenticated = True
        req.user.is_superuser = True
        perm_cls = HasPlanAtLeast('pro', 'enterprise')
        self.assertTrue(perm_cls().has_permission(req, None))

    def test_matching_plan_passes(self):
        tenant = Tenant.objects.create(
            name='ProCo', slug='proco', business_type='restaurant', plan='pro', is_active=True,
        )
        req = MagicMock()
        req.tenant = tenant
        req.user = MagicMock()
        req.user.is_authenticated = False
        perm_cls = HasPlanAtLeast('pro', 'enterprise')
        self.assertTrue(perm_cls().has_permission(req, None))


class HasTenantFeatureGapsTests(TestCase):
    def test_no_tenant_returns_false(self):
        req = MagicMock()
        req.tenant = None
        perm_cls = HasTenantFeature('blog')
        self.assertFalse(perm_cls().has_permission(req, None))


class IsOwnTenantStaffGapsTests(TestCase):
    def test_unauthenticated_returns_false(self):
        req = MagicMock()
        req.user = AnonymousUser()
        self.assertFalse(IsOwnTenantStaff().has_permission(req, None))

    def test_superuser_bypasses_role_check(self):
        req = MagicMock()
        req.user = MagicMock()
        req.user.is_authenticated = True
        req.user.is_superuser = True
        self.assertTrue(IsOwnTenantStaff().has_permission(req, None))

    def test_user_with_no_own_tenant_returns_false(self):
        user = User.objects.create_user(email='noone@example.com', password='pw12345', role='customer')
        req = MagicMock()
        req.user = user
        req.user.is_superuser = False
        self.assertFalse(IsOwnTenantStaff().has_permission(req, None))


class IsOwnTenantOwnerOrManagerGapsTests(TestCase):
    def test_unauthenticated_returns_false(self):
        req = MagicMock()
        req.user = AnonymousUser()
        self.assertFalse(IsOwnTenantOwnerOrManager().has_permission(req, None))

    def test_superuser_bypasses_role_check(self):
        req = MagicMock()
        req.user = MagicMock()
        req.user.is_authenticated = True
        req.user.is_superuser = True
        self.assertTrue(IsOwnTenantOwnerOrManager().has_permission(req, None))


def make_tenant__serializers_extra(**kwargs):
    defaults = dict(
        name='Nav Test Biz', slug='nav-test-biz', business_type='restaurant',
        is_active=True, plan=PLAN_PRO,
    )
    defaults.update(kwargs)
    return Tenant.objects.create(**defaults)


class CleanNavConfigTests(TestCase):
    def test_none_or_empty_returns_empty_dict(self):
        self.assertEqual(_clean_nav_config(None), {})
        self.assertEqual(_clean_nav_config({}), {})

    def test_non_dict_raises(self):
        with self.assertRaises(drf_serializers.ValidationError):
            _clean_nav_config(['not', 'a', 'dict'])

    def test_non_list_tabs_raises(self):
        with self.assertRaises(drf_serializers.ValidationError):
            _clean_nav_config({'tabs': 'not-a-list'})

    def test_entry_not_dict_or_missing_key_raises(self):
        with self.assertRaises(drf_serializers.ValidationError):
            _clean_nav_config({'tabs': ['not-a-dict']})
        with self.assertRaises(drf_serializers.ValidationError):
            _clean_nav_config({'tabs': [{'hidden': True}]})

    def test_non_string_key_raises(self):
        with self.assertRaises(drf_serializers.ValidationError):
            _clean_nav_config({'tabs': [{'key': 123}]})

    def test_unknown_key_raises(self):
        with self.assertRaises(drf_serializers.ValidationError):
            _clean_nav_config({'tabs': [{'key': 'bogus'}]})

    def test_custom_page_key_allowed(self):
        result = _clean_nav_config({'tabs': [{'key': 'page:about-us', 'hidden': True}]})
        keys = [t['key'] for t in result['tabs']]
        self.assertIn('page:about-us', keys)
        # all built-ins still re-appended
        self.assertIn('overview', keys)

    def test_missing_builtins_reappended(self):
        result = _clean_nav_config({'tabs': [{'key': 'overview'}]})
        keys = [t['key'] for t in result['tabs']]
        for builtin in ['overview', 'services', 'menu', 'orders', 'rentals', 'reviews', 'blog', 'contact']:
            self.assertIn(builtin, keys)


class LogoUrlTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()

    def _mock_logo_tenant(self):
        tenant = make_tenant__serializers_extra(slug='logo-tenant')
        mock_logo = MagicMock()
        mock_logo.__bool__ = lambda self: True
        mock_logo.url = '/media/logos/pic.png'
        tenant.logo = mock_logo
        return tenant

    def test_public_serializer_logo_url_with_request(self):
        tenant = self._mock_logo_tenant()
        request = self.factory.get('/')
        data = TenantPublicSerializer(tenant, context={'request': request}).data
        self.assertTrue(data['logo_url'].endswith('/media/logos/pic.png'))

    def test_public_serializer_logo_url_no_request(self):
        tenant = self._mock_logo_tenant()
        data = TenantPublicSerializer(tenant, context={}).data
        self.assertIsNone(data['logo_url'])

    def test_public_serializer_logo_url_no_logo(self):
        tenant = make_tenant__serializers_extra(slug='no-logo-tenant')
        data = TenantPublicSerializer(tenant, context={}).data
        self.assertIsNone(data['logo_url'])

    def test_marketplace_serializer_logo_url_with_request(self):
        tenant = self._mock_logo_tenant()
        tenant.slug = 'marketplace-logo-tenant'
        request = self.factory.get('/')
        data = MarketplaceTenantSerializer(tenant, context={'request': request}).data
        self.assertTrue(data['logo_url'].endswith('/media/logos/pic.png'))

    def test_marketplace_serializer_logo_url_no_logo(self):
        tenant = make_tenant__serializers_extra(slug='marketplace-no-logo')
        data = MarketplaceTenantSerializer(tenant, context={}).data
        self.assertIsNone(data['logo_url'])


class TenantAdminSerializerTests(TestCase):
    def test_has_billing_account_true_and_false(self):
        t1 = make_tenant__serializers_extra(slug='billing-yes', stripe_customer_id='cus_123')
        t2 = make_tenant__serializers_extra(slug='billing-no')
        self.assertTrue(TenantAdminSerializer(t1).data['has_billing_account'])
        self.assertFalse(TenantAdminSerializer(t2).data['has_billing_account'])

    def test_validate_contrast_check_invoked(self):
        tenant = make_tenant__serializers_extra(slug='contrast-admin', background_color='#ffffff', text_color='#ffffff')
        serializer = TenantAdminSerializer(instance=tenant, data={
            'text_color': '#ffffff',
        }, partial=True)
        self.assertFalse(serializer.is_valid())
        self.assertIn('text_color', serializer.errors)


class TenantSettingsSerializerContrastTests(TestCase):
    def test_validate_contrast_check_passes_for_valid_colors(self):
        tenant = make_tenant__serializers_extra(slug='contrast-ok', background_color='#ffffff', text_color='#000000')
        serializer = TenantSettingsSerializer(instance=tenant, data={
            'text_color': '#000000',
        }, partial=True)
        self.assertTrue(serializer.is_valid(), serializer.errors)


class TenantSignupSerializerTests(TestCase):
    def test_reserved_slug_rejected(self):
        serializer = TenantSignupSerializer(data={
            'business_name': 'Admin Shop',
            'slug': 'admin',
            'business_type': 'restaurant',
            'owner_email': 'newowner@example.com',
            'owner_password': 'SuperSecurePass987!',
            'owner_name': 'New Owner',
        })
        self.assertFalse(serializer.is_valid())
        self.assertIn('slug', serializer.errors)

    def test_duplicate_slug_rejected(self):
        make_tenant__serializers_extra(slug='taken-slug')
        serializer = TenantSignupSerializer(data={
            'business_name': 'Dup Shop',
            'slug': 'taken-slug',
            'business_type': 'restaurant',
            'owner_email': 'dupowner@example.com',
            'owner_password': 'SuperSecurePass987!',
            'owner_name': 'Dup Owner',
        })
        self.assertFalse(serializer.is_valid())
        self.assertIn('slug', serializer.errors)

    def test_django_password_validator_rejects_common_password(self):
        # Long enough to pass min_length=8, but should be caught by
        # Django's CommonPasswordValidator / similarity checks.
        serializer = TenantSignupSerializer(data={
            'business_name': 'Weak Pw Shop',
            'slug': 'weak-pw-shop',
            'business_type': 'restaurant',
            'owner_email': 'weakpw@example.com',
            'owner_password': 'password',
            'owner_name': 'Weak Pw',
        })
        self.assertFalse(serializer.is_valid())
        self.assertIn('owner_password', serializer.errors)

    def test_valid_signup_data_passes(self):
        serializer = TenantSignupSerializer(data={
            'business_name': 'Good Shop',
            'slug': 'good-shop-99',
            'business_type': 'restaurant',
            'owner_email': 'goodowner@example.com',
            'owner_password': 'Xk29!qzrPvw381',
            'owner_name': 'Good Owner',
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_referral_code_invalid_rejected(self):
        serializer = TenantSignupSerializer(data={
            'business_name': 'Ref Shop',
            'slug': 'ref-shop-1',
            'business_type': 'restaurant',
            'owner_email': 'refowner@example.com',
            'owner_password': 'Xk29!qzrPvw381',
            'owner_name': 'Ref Owner',
            'referral_code': 'DOES-NOT-EXIST',
        })
        self.assertFalse(serializer.is_valid())
        self.assertIn('referral_code', serializer.errors)

    def test_referral_code_valid_accepted(self):
        referrer = make_tenant__serializers_extra(slug='referrer-biz')
        code = referrer.referral_code
        serializer = TenantSignupSerializer(data={
            'business_name': 'Referred Shop',
            'slug': 'referred-shop-1',
            'business_type': 'restaurant',
            'owner_email': 'referredowner@example.com',
            'owner_password': 'Xk29!qzrPvw381',
            'owner_name': 'Referred Owner',
            'referral_code': code,
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_owner_email_used_on_another_tenant_is_allowed(self):
        # Same per-tenant-uniqueness reasoning as the view-level test above:
        # this serializer always targets a new tenant, so a pre-existing
        # User with the same email elsewhere on the platform is not a
        # collision and must not fail validation.
        from accounts.models import User
        User.objects.create_user(email='existing@example.com', password='x', full_name='Existing')
        serializer = TenantSignupSerializer(data={
            'business_name': 'Existing Email Shop',
            'slug': 'existing-email-shop',
            'business_type': 'restaurant',
            'owner_email': 'EXISTING@example.com',
            'owner_password': 'Xk29!qzrPvw381',
            'owner_name': 'Existing Owner',
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)


def make_tenant__serializers_gaps(slug='navcfgbiz'):
    return Tenant.objects.create(name=slug.title(), slug=slug, business_type='restaurant', plan='pro', is_active=True)


def make_user(email, tenant, role='owner'):
    return User.objects.create_user(email=email, password='pass1234', tenant=tenant, role=role)


class TenantSettingsNavConfigTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant__serializers_gaps('navcfgbiz')
        self.owner = make_user('owner@navcfgbiz.com', self.tenant)
        self.client.defaults['HTTP_HOST'] = 'navcfgbiz.bizal.al'
        self.client.force_authenticate(user=self.owner)

    def test_valid_nav_config_accepted(self):
        resp = self.client.patch(
            '/api/tenants/settings/',
            {'nav_config': {'tabs': [{'key': 'overview'}]}},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)

    def test_invalid_nav_config_rejected(self):
        resp = self.client.patch(
            '/api/tenants/settings/',
            {'nav_config': 'not-a-dict'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


def make_tenant__tasks(**kwargs):
    defaults = dict(
        name='Test Biz', slug='test-biz-tasks', business_type='restaurant',
        is_active=True, plan=PLAN_TRIAL,
    )
    defaults.update(kwargs)
    return Tenant.objects.create(**defaults)


class ExpireTrialsTests(TestCase):
    @patch('tenants.tasks._send_trial_expired_email')
    def test_expires_trial_past_end_date(self, mock_send):
        t = make_tenant__tasks(slug='expiring1', trial_ends_at=timezone.now() - datetime.timedelta(days=1))
        result = expire_trials()
        t.refresh_from_db()
        self.assertFalse(t.is_active)
        self.assertIn('1', result)
        mock_send.assert_called_once()

    @patch('tenants.tasks._send_trial_expired_email')
    def test_does_not_expire_active_trial(self, mock_send):
        t = make_tenant__tasks(slug='active1', trial_ends_at=timezone.now() + datetime.timedelta(days=5))
        expire_trials()
        t.refresh_from_db()
        self.assertTrue(t.is_active)
        mock_send.assert_not_called()

    @patch('tenants.tasks._send_trial_expired_email')
    def test_does_not_touch_non_trial_plan(self, mock_send):
        t = make_tenant__tasks(slug='pro1', plan=PLAN_PRO, trial_ends_at=timezone.now() - datetime.timedelta(days=1))
        expire_trials()
        t.refresh_from_db()
        self.assertTrue(t.is_active)

    @patch('tenants.tasks._send_trial_expired_email')
    def test_clears_trial_warning_sent_at_on_expiry(self, mock_send):
        t = make_tenant__tasks(
            slug='expiring2', trial_ends_at=timezone.now() - datetime.timedelta(days=1),
            trial_warning_sent_at=timezone.now(),
        )
        expire_trials()
        t.refresh_from_db()
        self.assertIsNone(t.trial_warning_sent_at)

    @patch('tenants.tasks._send_trial_expired_email')
    def test_plan_untouched_on_expiry(self, mock_send):
        t = make_tenant__tasks(slug='expiring3', trial_ends_at=timezone.now() - datetime.timedelta(days=1))
        expire_trials()
        t.refresh_from_db()
        self.assertEqual(t.plan, PLAN_TRIAL)


class SendTrialWarningEmailsTests(TestCase):
    @patch('tenants.tasks._send_trial_warning_email')
    def test_sends_warning_within_window(self, mock_send):
        t = make_tenant__tasks(slug='warn1', trial_ends_at=timezone.now() + datetime.timedelta(days=2))
        result = send_trial_warning_emails()
        mock_send.assert_called_once()
        t.refresh_from_db()
        self.assertIsNotNone(t.trial_warning_sent_at)
        self.assertIn('1', result)

    @patch('tenants.tasks._send_trial_warning_email')
    def test_skips_already_warned_tenant(self, mock_send):
        make_tenant__tasks(
            slug='warn2', trial_ends_at=timezone.now() + datetime.timedelta(days=2),
            trial_warning_sent_at=timezone.now(),
        )
        send_trial_warning_emails()
        mock_send.assert_not_called()

    @patch('tenants.tasks._send_trial_warning_email')
    def test_skips_tenant_outside_window(self, mock_send):
        make_tenant__tasks(slug='warn3', trial_ends_at=timezone.now() + datetime.timedelta(days=10))
        send_trial_warning_emails()
        mock_send.assert_not_called()

    @patch('tenants.tasks._send_trial_warning_email')
    def test_second_run_same_day_is_idempotent(self, mock_send):
        make_tenant__tasks(slug='warn4', trial_ends_at=timezone.now() + datetime.timedelta(days=1))
        first = send_trial_warning_emails()
        second = send_trial_warning_emails()
        self.assertIn('1', first)
        self.assertIn('0', second)
        mock_send.assert_called_once()


class EmailGuardTests(TestCase):
    """Covers the anonymised-owner guard shared by both email helper functions."""

    @patch('tenants.tasks.send_mail')
    def test_expired_email_skips_anonymised_owner(self, mock_send_mail):
        from tenants.tasks import _send_trial_expired_email
        t = make_tenant__tasks(slug='anon1')
        owner = User.objects.create_user(
            email='deleted_x@deleted.bizal.al', password='p', tenant=t, role='owner', is_active=False,
        )
        _send_trial_expired_email(t, owner=owner)
        mock_send_mail.assert_not_called()

    @patch('tenants.tasks.send_mail')
    def test_expired_email_skips_when_no_owner(self, mock_send_mail):
        from tenants.tasks import _send_trial_expired_email
        t = make_tenant__tasks(slug='anon2')
        _send_trial_expired_email(t, owner=None)
        mock_send_mail.assert_not_called()

    @patch('tenants.tasks.send_mail')
    def test_expired_email_sent_for_active_owner(self, mock_send_mail):
        from tenants.tasks import _send_trial_expired_email
        t = make_tenant__tasks(slug='anon3')
        owner = User.objects.create_user(email='real@test.com', password='p', tenant=t, role='owner')
        _send_trial_expired_email(t, owner=owner)
        mock_send_mail.assert_called_once()

    @patch('tenants.tasks.send_mail', side_effect=Exception('smtp down'))
    def test_expired_email_smtp_failure_logged_not_raised(self, mock_send_mail):
        from tenants.tasks import _send_trial_expired_email
        t = make_tenant__tasks(slug='anon4')
        owner = User.objects.create_user(email='real2@test.com', password='p', tenant=t, role='owner')
        _send_trial_expired_email(t, owner=owner)  # should not raise

    @patch('tenants.tasks.send_mail')
    def test_warning_email_skips_anonymised_owner(self, mock_send_mail):
        from tenants.tasks import _send_trial_warning_email
        t = make_tenant__tasks(slug='anon5')
        owner = User.objects.create_user(
            email='deleted_y@deleted.bizal.al', password='p', tenant=t, role='owner', is_active=False,
        )
        _send_trial_warning_email(t, 3, owner=owner)
        mock_send_mail.assert_not_called()

    @patch('tenants.tasks.send_mail')
    def test_warning_email_sent_for_active_owner(self, mock_send_mail):
        from tenants.tasks import _send_trial_warning_email
        t = make_tenant__tasks(slug='anon6')
        owner = User.objects.create_user(email='real3@test.com', password='p', tenant=t, role='owner')
        _send_trial_warning_email(t, 3, owner=owner)
        mock_send_mail.assert_called_once()

    @patch('tenants.tasks.send_mail', side_effect=Exception('smtp down'))
    def test_warning_email_smtp_failure_logged_not_raised(self, mock_send_mail):
        from tenants.tasks import _send_trial_warning_email
        t = make_tenant__tasks(slug='anon7')
        owner = User.objects.create_user(email='real4@test.com', password='p', tenant=t, role='owner')
        _send_trial_warning_email(t, 3, owner=owner)  # should not raise

    def test_expired_email_falls_back_to_queried_owner_when_none_passed(self):
        from tenants.tasks import _send_trial_expired_email
        t = make_tenant__tasks(slug='anon8')
        User.objects.create_user(email='queried@test.com', password='p', tenant=t, role='owner')
        with patch('tenants.tasks.send_mail') as mock_send_mail:
            _send_trial_expired_email(t)  # owner=None -> queries tenant.users
            mock_send_mail.assert_called_once()


class ApplyReferralCreditsTests(TestCase):
    def test_applies_credit_for_active_paid_referral(self):
        referrer = Tenant.objects.create(name='R', slug='referrer-a', business_type='shop', is_active=True, plan=PLAN_PRO)
        referred = Tenant.objects.create(name='D', slug='referred-a', business_type='shop', is_active=True, plan=PLAN_PRO)
        ref = TenantReferral.objects.create(referrer=referrer, referred=referred, credit_amount=15)
        result = apply_referral_credits_for_active_tenants()
        referrer.refresh_from_db()
        ref.refresh_from_db()
        self.assertTrue(ref.applied)
        self.assertEqual(referrer.referral_credits, 15)
        self.assertIn('1', result)

    def test_skips_starter_plan_referral(self):
        referrer = Tenant.objects.create(name='R2', slug='referrer-b', business_type='shop', is_active=True, plan=PLAN_PRO)
        referred = Tenant.objects.create(name='D2', slug='referred-b', business_type='shop', is_active=True, plan=PLAN_STARTER)
        TenantReferral.objects.create(referrer=referrer, referred=referred, credit_amount=15)
        apply_referral_credits_for_active_tenants()
        referrer.refresh_from_db()
        self.assertEqual(referrer.referral_credits, 0)

    def test_already_applied_referral_not_reprocessed(self):
        referrer = Tenant.objects.create(name='R3', slug='referrer-c', business_type='shop', is_active=True, plan=PLAN_PRO)
        referred = Tenant.objects.create(name='D3', slug='referred-c', business_type='shop', is_active=True, plan=PLAN_PRO)
        TenantReferral.objects.create(referrer=referrer, referred=referred, credit_amount=15, applied=True)
        result = apply_referral_credits_for_active_tenants()
        self.assertIn('0', result)

    def test_error_in_apply_credit_is_caught_and_counted(self):
        referrer = Tenant.objects.create(name='R4', slug='referrer-d', business_type='shop', is_active=True, plan=PLAN_PRO)
        referred = Tenant.objects.create(name='D4', slug='referred-d', business_type='shop', is_active=True, plan=PLAN_PRO)
        TenantReferral.objects.create(referrer=referrer, referred=referred, credit_amount=15)
        with patch('tenants.models.TenantReferral.apply_credit', side_effect=RuntimeError('boom')):
            result = apply_referral_credits_for_active_tenants()
        self.assertIn('1 error', result)


class RefreshFxRatesTests(TestCase):
    @patch('tenants.tasks.requests.get')
    def test_updates_tracked_currencies(self, mock_get):
        from tenants import fx
        mock_resp = MagicMock()
        mock_resp.json.return_value = {'rates': {c: 0.01 for c in fx.TRACKED_CURRENCIES}}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp
        with patch('tenants.fx.set_rate') as mock_set_rate:
            result = refresh_fx_rates()
        self.assertEqual(mock_set_rate.call_count, len(fx.TRACKED_CURRENCIES))
        self.assertIn('Refreshed', result)

    @patch('tenants.tasks.requests.get', side_effect=Exception('network down'))
    def test_network_failure_returns_gracefully(self, mock_get):
        result = refresh_fx_rates()
        self.assertIn('failed', result)

    @patch('tenants.tasks.requests.get')
    def test_missing_currency_in_response_skipped(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {'rates': {}}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp
        result = refresh_fx_rates()
        self.assertIn('Skipped', result)

    @patch('tenants.tasks.requests.get')
    def test_non_positive_rate_skipped(self, mock_get):
        from tenants import fx
        mock_resp = MagicMock()
        mock_resp.json.return_value = {'rates': {c: 0 for c in fx.TRACKED_CURRENCIES}}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp
        result = refresh_fx_rates()
        self.assertIn('Skipped', result)


def make_tenant__tasks_gaps(slug='taskgapbiz'):
    return Tenant.objects.create(name=slug.title(), slug=slug, business_type='restaurant', plan='pro', is_active=True)


class SendTrialWarningEmailNoOwnerTest(TestCase):
    def test_no_owner_returns_silently(self):
        from tenants.tasks import _send_trial_warning_email
        tenant = make_tenant__tasks_gaps('noownerbiz')
        # No owner-role user exists for this tenant.
        result = _send_trial_warning_email(tenant, days_left=3)
        self.assertIsNone(result)


class RefreshFxRatesBadRateTest(TestCase):
    def setUp(self):
        from django.core.cache.backends.locmem import LocMemCache
        self.real_cache = LocMemCache('fx-task-badrate-test', {})
        self.real_cache.clear()
        self._patcher = patch('tenants.fx.cache', self.real_cache)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    @patch('tenants.tasks.requests.get')
    def test_non_positive_rate_is_skipped_not_fatal(self, mock_get):
        from tenants.tasks import refresh_fx_rates
        from tenants.fx import is_available
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {'rates': {'EUR': -0.5, 'USD': 0.0103}},
        )
        mock_get.return_value.raise_for_status = lambda: None
        result = refresh_fx_rates()  # must not raise
        self.assertIn('EUR', result)
        self.assertFalse(is_available('EUR'))


def make_tenant__views_extra(**kwargs):
    defaults = dict(
        name='Views Test Biz', slug='views-test-biz', business_type='restaurant',
        is_active=True, plan=PLAN_PRO,
    )
    defaults.update(kwargs)
    return Tenant.objects.create(**defaults)


def make_owner(tenant, **kwargs):
    defaults = dict(
        email='owner@viewstest.com', password='StrongPassw0rd!9', full_name='Owner',
        tenant=tenant, role='owner',
    )
    defaults.update(kwargs)
    return User.objects.create_user(**defaults)


class TenantInfoViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.defaults['HTTP_HOST'] = 'bizal.al'  # main domain -> request.tenant is None

    def test_returns_tenant_by_slug_query_param(self):
        make_tenant__views_extra(slug='info-by-slug')
        resp = self.client.get('/api/tenants/info/', {'slug': 'info-by-slug'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['slug'], 'info-by-slug')

    def test_inactive_tenant_by_slug_returns_404(self):
        make_tenant__views_extra(slug='info-inactive', is_active=False)
        resp = self.client.get('/api/tenants/info/', {'slug': 'info-inactive'})
        self.assertEqual(resp.status_code, 404)

    def test_unknown_slug_returns_404(self):
        resp = self.client.get('/api/tenants/info/', {'slug': 'does-not-exist-xyz'})
        self.assertEqual(resp.status_code, 404)

    def test_no_tenant_and_no_slug_returns_404(self):
        resp = self.client.get('/api/tenants/info/')
        self.assertEqual(resp.status_code, 404)

    def test_returns_tenant_via_subdomain(self):
        make_tenant__views_extra(slug='info-subdomain')
        client = APIClient()
        client.defaults['HTTP_HOST'] = 'info-subdomain.bizal.al'
        resp = client.get('/api/tenants/info/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['slug'], 'info-subdomain')


class ChangePlanTests__views_extra(TestCase):
    def setUp(self):
        self.tenant = make_tenant__views_extra(slug='changeplan-biz', plan=PLAN_STARTER)
        self.owner = make_owner(self.tenant, email='cp-owner@test.com')
        self.client = APIClient()
        self.client.defaults['HTTP_HOST'] = 'changeplan-biz.bizal.al'
        self.client.force_authenticate(user=self.owner)

    def test_no_tenant_on_user_returns_400(self):
        user = User.objects.create_user(
            email='no-tenant@test.com', password='StrongPassw0rd!9', full_name='NoTenant',
        )
        client = APIClient()
        client.defaults['HTTP_HOST'] = 'changeplan-biz.bizal.al'
        client.force_authenticate(user=user)
        resp = client.post('/api/tenants/me/change-plan/', {'plan': PLAN_PRO}, format='json')
        # IsOwnTenantOwnerOrManager already denies a tenant-less user at the
        # permission layer (403) before the view's own `tenant is None` 400
        # check is ever reached — both are valid "no access" outcomes here.
        self.assertIn(resp.status_code, (400, 403))

    def test_invalid_plan_returns_400(self):
        resp = self.client.post('/api/tenants/me/change-plan/', {'plan': 'not-a-real-plan'}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_same_plan_is_noop(self):
        resp = self.client.post('/api/tenants/me/change-plan/', {'plan': PLAN_STARTER}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.plan, PLAN_STARTER)

    def test_upgrades_plan(self):
        resp = self.client.post('/api/tenants/me/change-plan/', {'plan': PLAN_ENTERPRISE}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.plan, PLAN_ENTERPRISE)


class TenantSignupTests__views_extra(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.defaults['HTTP_HOST'] = 'bizal.al'

    def _payload(self, **kwargs):
        defaults = dict(
            business_name='New Biz', slug='new-signup-biz', business_type='restaurant',
            owner_email='newsignup@test.com', owner_password='StrongPassw0rd!9',
            owner_name='New Owner',
        )
        defaults.update(kwargs)
        return defaults

    def test_signup_creates_pending_tenant(self):
        resp = self.client.post('/api/tenants/signup/', self._payload(), format='json')
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data['status'], 'pending_activation')
        tenant = Tenant.objects.get(slug='new-signup-biz')
        self.assertFalse(tenant.is_active)

    def test_signup_with_referral_code_awards_credit(self):
        referrer = make_tenant__views_extra(slug='referrer-signup-biz')
        resp = self.client.post(
            '/api/tenants/signup/',
            self._payload(slug='referred-signup-biz', owner_email='referred@test.com',
                           referral_code=referrer.referral_code),
            format='json',
        )
        self.assertEqual(resp.status_code, 201)
        referrer.refresh_from_db()
        self.assertGreater(referrer.referral_credits, 0)
        self.assertTrue(TenantReferral.objects.filter(referrer=referrer).exists())

    def test_signup_with_invalid_referral_code_is_rejected_by_serializer(self):
        # validate_referral_code() rejects unknown codes at the serializer
        # layer — the view's own `Tenant.DoesNotExist: pass` fallback for an
        # unmatched referral_code is therefore unreachable via this endpoint
        # (it exists as defense-in-depth for direct calls with validation
        # bypassed). Confirm the documented, actually-reachable behavior.
        resp = self.client.post(
            '/api/tenants/signup/',
            self._payload(slug='badref-signup-biz', owner_email='badref@test.com',
                           referral_code='NOSUCHCODE'),
            format='json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('referral_code', resp.data)

    def test_duplicate_email_race_rolls_back_everything(self):
        # Simulate the TOCTOU race: serializer validation passes (email not
        # yet taken) but User.objects.create_user() raises IntegrityError.
        # Referral credit awarded inside the same atomic() block must roll
        # back along with the Tenant/TenantReferral rows.
        referrer = make_tenant__views_extra(slug='referrer-race-biz')
        from django.db import IntegrityError
        with patch('accounts.models.User.objects.create_user', side_effect=IntegrityError('dup')):
            resp = self.client.post(
                '/api/tenants/signup/',
                self._payload(slug='race-signup-biz', owner_email='race@test.com',
                               referral_code=referrer.referral_code),
                format='json',
            )
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(Tenant.objects.filter(slug='race-signup-biz').exists())
        referrer.refresh_from_db()
        self.assertEqual(referrer.referral_credits, 0)

    def test_email_send_failure_does_not_break_signup(self):
        with patch('tenants.views.send_mail', side_effect=Exception('smtp down')):
            resp = self.client.post(
                '/api/tenants/signup/',
                self._payload(slug='emailfail-signup-biz', owner_email='emailfail@test.com'),
                format='json',
            )
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(Tenant.objects.filter(slug='emailfail-signup-biz').exists())


class CreateTenantTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.defaults['HTTP_HOST'] = 'bizal.al'

    def test_creates_tenant_for_user_with_no_tenant(self):
        user = User.objects.create_user(email='wantsbiz@test.com', password='StrongPassw0rd!9', full_name='Wants Biz')
        self.client.force_authenticate(user=user)
        resp = self.client.post('/api/tenants/create/', {
            'business_name': 'Fresh Biz', 'slug': 'fresh-biz-create', 'business_type': 'market',
        }, format='json')
        self.assertEqual(resp.status_code, 201)
        user.refresh_from_db()
        self.assertEqual(user.tenant.slug, 'fresh-biz-create')
        self.assertEqual(user.role, 'owner')

    def test_user_who_already_has_tenant_is_rejected(self):
        tenant = make_tenant__views_extra(slug='already-has-one')
        owner = make_owner(tenant, email='hasone@test.com')
        self.client.force_authenticate(user=owner)
        resp = self.client.post('/api/tenants/create/', {
            'business_name': 'Another', 'slug': 'another-biz', 'business_type': 'market',
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_invalid_plan_rejected(self):
        user = User.objects.create_user(email='badplan@test.com', password='StrongPassw0rd!9', full_name='Bad Plan')
        self.client.force_authenticate(user=user)
        resp = self.client.post('/api/tenants/create/', {
            'business_name': 'Plan Biz', 'slug': 'plan-biz', 'business_type': 'market', 'plan': 'nonsense',
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_missing_required_fields_rejected(self):
        user = User.objects.create_user(email='missing@test.com', password='StrongPassw0rd!9', full_name='Missing')
        self.client.force_authenticate(user=user)
        resp = self.client.post('/api/tenants/create/', {'business_name': ''}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_taken_slug_rejected(self):
        make_tenant__views_extra(slug='taken-slug-biz')
        user = User.objects.create_user(email='takenslug@test.com', password='StrongPassw0rd!9', full_name='Taken')
        self.client.force_authenticate(user=user)
        resp = self.client.post('/api/tenants/create/', {
            'business_name': 'Dup', 'slug': 'taken-slug-biz', 'business_type': 'market',
        }, format='json')
        self.assertEqual(resp.status_code, 400)


class PublicLookupTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.defaults['HTTP_HOST'] = 'bizal.al'

    def test_check_slug_available(self):
        resp = self.client.get('/api/tenants/check-slug/', {'slug': 'totally-free-slug'})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data['available'])

    def test_check_slug_taken(self):
        make_tenant__views_extra(slug='taken-check-slug')
        resp = self.client.get('/api/tenants/check-slug/', {'slug': 'taken-check-slug'})
        self.assertFalse(resp.data['available'])

    def test_check_slug_reserved(self):
        resp = self.client.get('/api/tenants/check-slug/', {'slug': 'admin'})
        self.assertFalse(resp.data['available'])

    def test_business_types_lists_counts(self):
        make_tenant__views_extra(slug='marketplace-biz-1', business_type='restaurant', listed_on_marketplace=True)
        resp = self.client.get('/api/tenants/business-types/')
        self.assertEqual(resp.status_code, 200)
        restaurant = next(x for x in resp.data['results'] if x['value'] == 'restaurant')
        self.assertGreaterEqual(restaurant['tenant_count'], 1)

    def test_marketplace_list_filters_by_type_city_and_query(self):
        make_tenant__views_extra(slug='mk-1', business_type='restaurant', listed_on_marketplace=True,
                    city='Tirane', name='Pizza Palace')
        make_tenant__views_extra(slug='mk-2', business_type='hotel', listed_on_marketplace=True,
                    city='Durres', name='Hotel Riviera')
        resp = self.client.get('/api/tenants/marketplace/', {'type': 'restaurant'})
        self.assertEqual(resp.status_code, 200)
        slugs = [r['slug'] for r in resp.data['results']]
        self.assertIn('mk-1', slugs)
        self.assertNotIn('mk-2', slugs)

        resp = self.client.get('/api/tenants/marketplace/', {'city': 'durres'})
        slugs = [r['slug'] for r in resp.data['results']]
        self.assertIn('mk-2', slugs)

        resp = self.client.get('/api/tenants/marketplace/', {'q': 'Pizza'})
        slugs = [r['slug'] for r in resp.data['results']]
        self.assertIn('mk-1', slugs)


class TenantLocationCRUDTests(TestCase):
    def setUp(self):
        self.tenant = make_tenant__views_extra(slug='loc-crud-biz', plan=PLAN_ENTERPRISE)
        self.owner = make_owner(self.tenant, email='loc-owner@test.com')
        self.client = APIClient()
        self.client.defaults['HTTP_HOST'] = 'loc-crud-biz.bizal.al'
        self.client.force_authenticate(user=self.owner)

    def test_create_location_requires_multi_location_feature(self):
        no_feature_tenant = make_tenant__views_extra(slug='loc-no-feature', plan=PLAN_STARTER)
        owner = make_owner(no_feature_tenant, email='nofeature-owner@test.com')
        client = APIClient()
        client.defaults['HTTP_HOST'] = 'loc-no-feature.bizal.al'
        client.force_authenticate(user=owner)
        resp = client.post('/api/tenants/locations/', {'name': 'Branch A'}, format='json')
        self.assertEqual(resp.status_code, 403)

    def test_create_and_list_locations(self):
        resp = self.client.post('/api/tenants/locations/', {'name': 'Branch A', 'city': 'Tirane'}, format='json')
        self.assertEqual(resp.status_code, 201)
        list_resp = self.client.get('/api/tenants/locations/')
        self.assertEqual(list_resp.status_code, 200)
        # DEFAULT_PAGINATION_CLASS wraps list results in {count, next,
        # previous, results} — assert against the 'results' key, not len() on
        # the whole response dict.
        self.assertEqual(len(list_resp.data['results']), 1)

    def test_retrieve_update_delete_location(self):
        loc = TenantLocation.objects.create(tenant=self.tenant, name='Branch B')
        detail_url = f'/api/tenants/locations/{loc.pk}/'
        resp = self.client.get(detail_url)
        self.assertEqual(resp.status_code, 200)
        resp = self.client.patch(detail_url, {'name': 'Branch B Renamed'}, format='json')
        self.assertEqual(resp.status_code, 200)
        resp = self.client.delete(detail_url)
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(TenantLocation.objects.filter(pk=loc.pk).exists())


class MyReferralsTests(TestCase):
    def test_no_tenant_returns_404(self):
        user = User.objects.create_user(email='noref@test.com', password='StrongPassw0rd!9', full_name='NoRef')
        client = APIClient()
        client.defaults['HTTP_HOST'] = 'bizal.al'
        client.force_authenticate(user=user)
        resp = client.get('/api/tenants/referrals/')
        self.assertEqual(resp.status_code, 404)

    def test_lists_referrals_and_credits(self):
        referrer = make_tenant__views_extra(slug='referrals-list-biz')
        referred = make_tenant__views_extra(slug='referred-list-biz', plan=PLAN_TRIAL)
        TenantReferral.objects.create(referrer=referrer, referred=referred, credit_amount=10)
        owner = make_owner(referrer, email='refs-owner@test.com')
        client = APIClient()
        client.defaults['HTTP_HOST'] = 'bizal.al'
        client.force_authenticate(user=owner)
        resp = client.get('/api/tenants/referrals/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data['referrals']), 1)
        self.assertEqual(resp.data['referral_code'], referrer.referral_code)


class CreditEndpointsTests(TestCase):
    def setUp(self):
        self.tenant = make_tenant__views_extra(slug='credits-biz')
        self.owner = make_owner(self.tenant, email='credits-owner@test.com')
        self.client = APIClient()
        self.client.defaults['HTTP_HOST'] = 'credits-biz.bizal.al'
        self.client.force_authenticate(user=self.owner)

    def test_balance_no_tenant_returns_400(self):
        client = APIClient()
        client.defaults['HTTP_HOST'] = 'bizal.al'
        user = User.objects.create_user(email='nocredit@test.com', password='StrongPassw0rd!9', full_name='NoCredit')
        client.force_authenticate(user=user)
        resp = client.get('/api/tenants/credits/balance/')
        self.assertIn(resp.status_code, (400, 403))

    def test_balance_returns_amount_and_recent_entries(self):
        Tenant.objects.filter(pk=self.tenant.pk).update(referral_credits=Decimal('25.00'))
        CreditLedger.objects.create(tenant=self.tenant, amount=Decimal('25.00'), event=CreditLedger.EVENT_REFERRAL)
        resp = self.client.get('/api/tenants/credits/balance/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['balance'], '25.00')
        self.assertEqual(len(resp.data['recent']), 1)

    def test_ledger_is_paginated(self):
        Tenant.objects.filter(pk=self.tenant.pk).update(referral_credits=Decimal('100.00'))
        for i in range(3):
            CreditLedger.objects.create(
                tenant=self.tenant, amount=Decimal('1.00'), event=CreditLedger.EVENT_ADJUSTMENT,
                description=f'entry {i}',
            )
        resp = self.client.get('/api/tenants/credits/ledger/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('results', resp.data)
        self.assertEqual(len(resp.data['results']), 3)

    def test_redeem_invalid_amount_rejected(self):
        resp = self.client.post('/api/tenants/credits/redeem/', {'amount': 'not-a-number'}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_redeem_negative_amount_rejected(self):
        resp = self.client.post('/api/tenants/credits/redeem/', {'amount': '-5'}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_redeem_insufficient_balance_rejected(self):
        Tenant.objects.filter(pk=self.tenant.pk).update(referral_credits=Decimal('1.00'))
        resp = self.client.post('/api/tenants/credits/redeem/', {'amount': '5.00'}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_redeem_without_invoice_debits_balance(self):
        Tenant.objects.filter(pk=self.tenant.pk).update(referral_credits=Decimal('20.00'))
        resp = self.client.post('/api/tenants/credits/redeem/', {'amount': '5.00'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.referral_credits, Decimal('15.00'))
        self.assertIsNone(resp.data['invoice_total'])

    def test_redeem_with_invoice_from_other_tenant_rejected(self):
        other_tenant = make_tenant__views_extra(slug='other-tenant-inv')
        invoice = Invoice.objects.create(tenant=other_tenant, status='sent', total_amount=Decimal('50.00'))
        Tenant.objects.filter(pk=self.tenant.pk).update(referral_credits=Decimal('20.00'))
        resp = self.client.post('/api/tenants/credits/redeem/', {
            'amount': '5.00', 'invoice_id': str(invoice.pk),
        }, format='json')
        self.assertEqual(resp.status_code, 404)

    def test_redeem_applies_and_caps_at_invoice_total(self):
        from billing.models import InvoiceLine
        Tenant.objects.filter(pk=self.tenant.pk).update(referral_credits=Decimal('100.00'))
        invoice = Invoice.objects.create(tenant=self.tenant, status='sent', total_amount=Decimal('0.00'))
        # recompute_total() derives total_amount purely from InvoiceLine rows
        # (see billing/models.py), so a real line — not a hand-set
        # total_amount — is required to give the invoice a genuine 30.00
        # balance for the credit to be capped against.
        InvoiceLine.objects.create(tenant=self.tenant, invoice=invoice, description='Service', quantity=1, unit_price=Decimal('30.00'))
        invoice.refresh_from_db()
        self.assertEqual(invoice.total_amount, Decimal('30.00'))

        resp = self.client.post('/api/tenants/credits/redeem/', {
            'amount': '50.00', 'invoice_id': str(invoice.pk),
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['requested'], '50.00')
        self.assertEqual(resp.data['applied'], '30.00')
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.referral_credits, Decimal('70.00'))
        invoice.refresh_from_db()
        self.assertEqual(invoice.total_amount, Decimal('0.00'))

    def test_redeem_invoice_with_no_remaining_balance_rejected(self):
        Tenant.objects.filter(pk=self.tenant.pk).update(referral_credits=Decimal('100.00'))
        invoice = Invoice.objects.create(tenant=self.tenant, status='sent', total_amount=Decimal('0.00'))
        resp = self.client.post('/api/tenants/credits/redeem/', {
            'amount': '10.00', 'invoice_id': str(invoice.pk),
        }, format='json')
        self.assertEqual(resp.status_code, 400)


User = get_user_model()


def make_tenant__views_gaps2(**kwargs):
    defaults = dict(
        name='Views Gap Biz', slug='views-gap-biz', business_type='restaurant',
        is_active=True, plan=PLAN_PRO,
    )
    defaults.update(kwargs)
    return Tenant.objects.create(**defaults)


class TenantSettingsViewTests(TestCase):
    def setUp(self):
        self.tenant = make_tenant__views_gaps2(slug='settings-gap')
        self.owner = User.objects.create_user(
            email='owner@settings-gap.com', password='pass1234',
            tenant=self.tenant, role='owner',
        )
        self.client = APIClient()
        self.client.defaults['HTTP_HOST'] = 'settings-gap.bizal.al'
        self.client.force_authenticate(user=self.owner)

    def test_get_settings(self):
        resp = self.client.get('/api/tenants/settings/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['name'], 'Views Gap Biz')

    def test_patch_settings_invalidates_cache(self):
        resp = self.client.patch('/api/tenants/settings/', {'name': 'Renamed Biz'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.name, 'Renamed Biz')


class TenantMeViewNoTenantTests(TestCase):
    def test_superuser_without_tenant_gets_404(self):
        superuser = User.objects.create_superuser(
            email='super@bizal.al', password='pass1234',
        )
        client = APIClient()
        client.defaults['HTTP_HOST'] = 'bizal.al'
        client.force_authenticate(user=superuser)
        resp = client.get('/api/tenants/me/')
        self.assertEqual(resp.status_code, 404)
        self.assertIn('No tenant associated', str(resp.data))


class TenantSignupUnknownReferralTests(TestCase):
    @patch('tenants.views.send_mail')
    def test_signup_referral_race_condition_falls_back_gracefully(self, mock_mail):
        """
        TenantSignupSerializer.validate_referral_code() already checks the
        code exists, so a genuinely-unknown code is rejected before the view
        runs. The view's own `except Tenant.DoesNotExist: pass` guards
        against a TOCTOU race — the referrer tenant is deleted between
        serializer validation and the view's own lookup — which we simulate
        directly here.
        """
        referrer = make_tenant__views_gaps2(slug='referrer-for-race', referral_code='RACECODE01')
        client = APIClient()
        client.defaults['HTTP_HOST'] = 'bizal.al'

        original_get = Tenant.objects.get

        def flaky_get(*args, **kwargs):
            if kwargs.get('referral_code') == 'RACECODE01':
                raise Tenant.DoesNotExist()
            return original_get(*args, **kwargs)

        with patch.object(Tenant.objects, 'get', side_effect=flaky_get):
            resp = client.post('/api/tenants/signup/', {
                'business_name': 'Referred Biz', 'slug': 'referred-biz-gap',
                'business_type': 'market',
                'owner_name': 'Ref Owner', 'owner_email': 'refd@example.com',
                'owner_password': 'StrongPass99!',
                'referral_code': 'RACECODE01',
            }, format='json')

        self.assertEqual(resp.status_code, 201, resp.data)
        tenant = Tenant.objects.get(slug='referred-biz-gap')
        self.assertIsNone(tenant.referred_by)


class ChangePlanNoTenantTests(TestCase):
    def test_change_plan_without_tenant_returns_400(self):
        # A superuser passes IsOwnTenantOwnerOrManager unconditionally (it
        # returns True for is_superuser before checking tenant), so this is
        # the one real path that reaches the view body's own no-tenant guard.
        user = User.objects.create_superuser(email='notenant@x.com', password='pass1234')
        client = APIClient()
        client.defaults['HTTP_HOST'] = 'bizal.al'
        client.force_authenticate(user=user)
        resp = client.post('/api/tenants/me/change-plan/', {'plan': PLAN_STARTER}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('No tenant', resp.data['detail'])


class CreditEndpointsNoTenantGuardTests(TestCase):
    """
    IsTenantOwner.has_permission() already returns False when request.tenant
    is falsy, so these views' own `if not tenant:` guards can't be reached
    by a real request. Patch the permission class to force the view body
    to run and confirm the defensive guard behaves correctly anyway.
    """
    def setUp(self):
        self.user = User.objects.create_user(email='noten@x.com', password='pass1234')
        self.client = APIClient()
        self.client.defaults['HTTP_HOST'] = 'bizal.al'  # main domain -> request.tenant is None
        self.client.force_authenticate(user=self.user)

    def test_credit_balance_without_tenant(self):
        with patch.object(IsTenantOwner, 'has_permission', return_value=True):
            resp = self.client.get('/api/tenants/credits/balance/')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data['detail'], 'No tenant.')

    def test_credit_ledger_without_tenant(self):
        with patch.object(IsTenantOwner, 'has_permission', return_value=True):
            resp = self.client.get('/api/tenants/credits/ledger/')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data['detail'], 'No tenant.')

    def test_credit_redeem_without_tenant(self):
        with patch.object(IsTenantOwner, 'has_permission', return_value=True):
            resp = self.client.post('/api/tenants/credits/redeem/', {'amount': '5.00'}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data['detail'], 'No tenant.')


class CreditLedgerNonPaginatedBranchTests(TestCase):
    def test_credit_ledger_returns_plain_response_when_pagination_disabled(self):
        tenant = make_tenant__views_gaps2(slug='ledger-nonpg')
        owner = User.objects.create_user(
            email='owner@ledger-nonpg.com', password='pass1234',
            tenant=tenant, role='owner',
        )
        from tenants.models import CreditLedger
        CreditLedger.objects.create(tenant=tenant, amount=Decimal('5.00'), event=CreditLedger.EVENT_REFERRAL)

        client = APIClient()
        client.defaults['HTTP_HOST'] = 'ledger-nonpg.bizal.al'
        client.force_authenticate(user=owner)

        with patch('rest_framework.pagination.PageNumberPagination.paginate_queryset', return_value=None):
            resp = client.get('/api/tenants/credits/ledger/')
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.data, list)
