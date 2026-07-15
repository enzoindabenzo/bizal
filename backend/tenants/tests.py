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


def make_tenant(**kwargs):
    defaults = dict(
        name='Test Biz', slug='test-biz', business_type='restaurant',
        is_active=True, plan=PLAN_PRO,
    )
    defaults.update(kwargs)
    return Tenant.objects.create(**defaults)


# ── Model tests ───────────────────────────────────────────────────────────────

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


# ── Middleware tests ──────────────────────────────────────────────────────────

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


# ── Feature coverage sanity check ─────────────────────────────────────────────

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


# ── TenantMeView permission check ──────────────────────────────────────────────

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


# ── tenant_signup tests ────────────────────────────────────────────────────────

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
        self.assertEqual(self.tenant.plan, 'trial')  # unchanged


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
        v66 FIX (LOW): check_slug must reject reserved slugs (admin, api,
        health, etc.) even though no Tenant row exists with that slug.
        TenantSignupSerializer already blocks these at submit time, so this
        was never a security gap — but before this fix the onboarding
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
            self.assertIs(wrapped2, dummy2)  # no-op passthrough


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
    def test_duplicate_email_rejected(self, mock_mail):
        from accounts.models import User
        User.objects.create_user(
            email='arta@test.com', password='pass', full_name='Existing',
        )
        resp = self.client.post(self.url, self.base_payload, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('owner_email', resp.data)

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
        # Trial clock is activation-gated (see HIGH-1 fix): signup must
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


# ── django-admin user list — tenant filter ──────────────────────────────────

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


# ── Theme: background/text contrast ─────────────────────────────────────────

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


# ── Self-service plan change ────────────────────────────────────────────────

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


# ── tenants/fx.py — FX conversion helpers ────────────────────────────────────

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
        self.assertIn('USD', result)  # reported in the skipped list


# ── credit_redeem endpoint ───────────────────────────────────────────────────

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
