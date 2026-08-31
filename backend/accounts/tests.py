from django.test import TestCase

from rest_framework.test import APIClient

from rest_framework import status

from accounts.models import User

from tenants.models import Tenant

from types import SimpleNamespace

from accounts.auth_backends import TenantAwareModelBackend

from unittest.mock import patch

from rest_framework_simplejwt.tokens import RefreshToken

from .models import User

from django.core.files.uploadedfile import SimpleUploadedFile


class AccountsTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(
            name='Test Business', slug='test', business_type='restaurant', plan='pro',
            is_active=True, onboarding_complete=True,
        )
        self.tenant2 = Tenant.objects.create(
            name='Other Business', slug='hertz', business_type='car_rental', plan='enterprise',
            is_active=True, onboarding_complete=True,
        )
        self.owner = User.objects.create_user(
            email='owner@test.com', password='pass1234', tenant=self.tenant, role='owner',
        )

    # ── Registration ──────────────────────────────────────────

    def test_register_on_tenant(self):
        self.client.defaults['HTTP_HOST'] = 'test.bizal.al'
        resp = self.client.post('/api/auth/register/', {
            'email': 'new@test.com', 'password': 'securepass123',
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_register_duplicate_email(self):
        User.objects.create_user(email='dup@test.com', password='pass1234', tenant=self.tenant)
        self.client.defaults['HTTP_HOST'] = 'test.bizal.al'
        resp = self.client.post('/api/auth/register/', {
            'email': 'dup@test.com', 'password': 'securepass123',
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    # ── Login ─────────────────────────────────────────────────

    def test_login_returns_tokens(self):
        self.client.defaults['HTTP_HOST'] = 'test.bizal.al'
        resp = self.client.post('/api/auth/login/', {
            'email': 'owner@test.com', 'password': 'pass1234',
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('access', resp.data)
        self.assertIn('refresh', resp.data)

    def test_cross_tenant_login_rejected(self):
        self.client.defaults['HTTP_HOST'] = 'hertz.bizal.al'
        resp = self.client.post('/api/auth/login/', {
            'email': 'owner@test.com', 'password': 'pass1234',
        })
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_non_staff_cannot_login_main_domain(self):
        self.client.defaults['HTTP_HOST'] = 'bizal.al'
        resp = self.client.post('/api/auth/login/', {
            'email': 'owner@test.com', 'password': 'pass1234',
        })
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    # ── Change password ───────────────────────────────────────

    def test_change_password_success(self):
        self.client.defaults['HTTP_HOST'] = 'test.bizal.al'
        self.client.force_authenticate(user=self.owner)
        resp = self.client.post('/api/auth/change-password/', {
            'old_password': 'pass1234', 'new_password': 'newpass5678',
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.check_password('newpass5678'))

    def test_change_password_wrong_old(self):
        self.client.defaults['HTTP_HOST'] = 'test.bizal.al'
        self.client.force_authenticate(user=self.owner)
        resp = self.client.post('/api/auth/change-password/', {
            'old_password': 'wrongpassword', 'new_password': 'newpass5678',
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_change_password_too_short(self):
        self.client.defaults['HTTP_HOST'] = 'test.bizal.al'
        self.client.force_authenticate(user=self.owner)
        resp = self.client.post('/api/auth/change-password/', {
            'old_password': 'pass1234', 'new_password': 'abc',
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_change_password_requires_auth(self):
        resp = self.client.post('/api/auth/change-password/', {
            'old_password': 'pass1234', 'new_password': 'newpass5678',
        })
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    # ── Password reset ────────────────────────────────────────

    def test_password_reset_request_existing_email(self):
        self.client.defaults['HTTP_HOST'] = 'test.bizal.al'
        resp = self.client.post('/api/auth/password-reset/', {
            'email': 'owner@test.com',
        })
        # Always 200 to avoid user enumeration
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_password_reset_request_email_shared_across_tenants(self):
        """
        Regression: email is intentionally not globally unique (a person can
        have a separate account on each tenant they interact with). A
        password-reset request from the main domain (no request.tenant) used
        to call User.objects.get(email=email) with no tenant filter, which
        raises MultipleObjectsReturned — and 500s — once that email exists on
        2+ tenants, instead of returning the generic 200 response.
        """
        User.objects.create_user(
            email='shared@example.com', password='pass1234',
            tenant=self.tenant, role='customer',
        )
        User.objects.create_user(
            email='shared@example.com', password='pass5678',
            tenant=self.tenant2, role='customer',
        )
        # No HTTP_HOST override => main domain, request.tenant is None.
        resp = self.client.post('/api/auth/password-reset/', {
            'email': 'shared@example.com',
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_password_reset_request_unknown_email(self):
        resp = self.client.post('/api/auth/password-reset/', {
            'email': 'nobody@example.com',
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_password_reset_confirm_invalid_token(self):
        resp = self.client.post('/api/auth/password-reset/confirm/', {
            'uid': 'bad-uid', 'token': 'bad-token', 'new_password': 'newpass5678',
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_password_reset_confirm_valid(self):
        from django.utils.http import urlsafe_base64_encode
        from django.utils.encoding import force_bytes
        from django.contrib.auth.tokens import default_token_generator
        uid = urlsafe_base64_encode(force_bytes(self.owner.pk))
        token = default_token_generator.make_token(self.owner)
        resp = self.client.post('/api/auth/password-reset/confirm/', {
            'uid': uid, 'token': token, 'new_password': 'brandnew5678',
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.check_password('brandnew5678'))

    def test_password_reset_confirm_rejects_common_password(self):
        """
        Regression test: PasswordResetConfirmView must run the full
        AUTH_PASSWORD_VALIDATORS suite (same as ChangePasswordView), not
        just a length check. A reset to a common password like
        "password1" (>= 8 chars, so the old length-only check would have
        let it through) must be rejected.
        """
        from django.utils.http import urlsafe_base64_encode
        from django.utils.encoding import force_bytes
        from django.contrib.auth.tokens import default_token_generator
        uid = urlsafe_base64_encode(force_bytes(self.owner.pk))
        token = default_token_generator.make_token(self.owner)
        resp = self.client.post('/api/auth/password-reset/confirm/', {
            'uid': uid, 'token': token, 'new_password': 'password1',
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.owner.refresh_from_db()
        self.assertFalse(self.owner.check_password('password1'))

    # ── Email verification (token generator separation) ────────────

    def test_email_verification_confirm_with_valid_token(self):
        """The dedicated email-verification token is accepted by its own
        endpoint and flips is_email_verified."""
        from django.utils.http import urlsafe_base64_encode
        from django.utils.encoding import force_bytes
        from accounts.tokens import email_verification_token_generator
        uid = urlsafe_base64_encode(force_bytes(self.owner.pk))
        token = email_verification_token_generator.make_token(self.owner)
        resp = self.client.get(f'/api/auth/verify-email/{uid}/{token}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.is_email_verified)

    def test_password_reset_token_rejected_by_email_verification_endpoint(self):
        """
        Regression test: a token minted by default_token_generator
        (the password-reset generator) must NOT be accepted by
        EmailVerificationConfirmView. If both flows shared
        one generator, so a password-reset email could be replayed here
        to mark an account verified without the user ever clicking a
        verification link.
        """
        from django.utils.http import urlsafe_base64_encode
        from django.utils.encoding import force_bytes
        from django.contrib.auth.tokens import default_token_generator
        uid = urlsafe_base64_encode(force_bytes(self.owner.pk))
        password_reset_token = default_token_generator.make_token(self.owner)
        resp = self.client.get(f'/api/auth/verify-email/{uid}/{password_reset_token}/')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.owner.refresh_from_db()
        self.assertFalse(self.owner.is_email_verified)

    def test_email_verification_token_rejected_by_password_reset_endpoint(self):
        """
        Regression test, opposite direction: a token minted by
        email_verification_token_generator must NOT be accepted by
        PasswordResetConfirmView.
        """
        from django.utils.http import urlsafe_base64_encode
        from django.utils.encoding import force_bytes
        from accounts.tokens import email_verification_token_generator
        uid = urlsafe_base64_encode(force_bytes(self.owner.pk))
        verification_token = email_verification_token_generator.make_token(self.owner)
        resp = self.client.post('/api/auth/password-reset/confirm/', {
            'uid': uid, 'token': verification_token, 'new_password': 'shouldnotwork123',
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.owner.refresh_from_db()
        self.assertFalse(self.owner.check_password('shouldnotwork123'))

    # ── App config ────────────────────────────────────────────

    def test_app_name(self):
        from django.apps import apps
        self.assertEqual(apps.get_app_config('accounts').name, 'accounts')

    # ── Cross-tenant guard edge cases (Fix: user.tenant=None bypass) ─────────

    def test_platform_user_with_no_tenant_blocked_at_subdomain(self):
        """
        Një platform user (tenant=None, jo superuser) nuk duhet të hyjë
        te asnjë subdomain tenant — edhe pse user.tenant është None dhe
        kushti i vjetër `user.tenant and ...` e linte të kalonte.
        """
        User.objects.create_user(
            email='platform@bizal.al', password='pass1234',
            tenant=None, role='customer', is_staff=False,
        )
        self.client.defaults['HTTP_HOST'] = 'test.bizal.al'
        resp = self.client.post('/api/auth/login/', {
            'email': 'platform@bizal.al', 'password': 'pass1234',
        })
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_superuser_blocked_at_tenant_subdomain_login(self):
        """
        Superadmin-ët nuk duhet të logohen te subdomain-et e tenant-ëve
        nëpërmjet /api/auth/login/ — ata përdorin /admin/ direkt.
        """
        User.objects.create_user(
            email='super@bizal.al', password='superpass1234',
            tenant=None, is_superuser=True, is_staff=True,
        )
        self.client.defaults['HTTP_HOST'] = 'test.bizal.al'
        resp = self.client.post('/api/auth/login/', {
            'email': 'super@bizal.al', 'password': 'superpass1234',
        })
        # Superadmins are now explicitly blocked from tenant subdomains
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


def make_tenant(slug):
    return Tenant.objects.create(name=slug.title(), slug=slug, business_type='restaurant', plan='pro', is_active=True)


class TenantAwareBackendMissingCredentialsTests(TestCase):
    """Covers line 31: early return when email or password is missing."""

    def test_missing_password_returns_none(self):
        backend = TenantAwareModelBackend()
        result = backend.authenticate(None, username='a@b.com', password=None)
        self.assertIsNone(result)

    def test_missing_email_returns_none(self):
        backend = TenantAwareModelBackend()
        result = backend.authenticate(None, username=None, password='pass1234')
        self.assertIsNone(result)


class TenantAwareBackendNoRequestTests(TestCase):
    """Covers lines 37-46: the request=None management-command fallback path."""

    def setUp(self):
        self.tenant = make_tenant('nrbiz')

    def test_no_request_nonexistent_user_returns_none(self):
        backend = TenantAwareModelBackend()
        result = backend.authenticate(None, username='ghost@nrbiz.com', password='pass1234')
        self.assertIsNone(result)

    def test_no_request_correct_password_authenticates(self):
        User.objects.create_user(email='solo@nrbiz.com', password='pass1234', tenant=self.tenant)
        backend = TenantAwareModelBackend()
        result = backend.authenticate(None, username='solo@nrbiz.com', password='pass1234')
        self.assertIsNotNone(result)
        self.assertEqual(result.email, 'solo@nrbiz.com')

    def test_no_request_wrong_password_returns_none(self):
        User.objects.create_user(email='solo2@nrbiz.com', password='pass1234', tenant=self.tenant)
        backend = TenantAwareModelBackend()
        result = backend.authenticate(None, username='solo2@nrbiz.com', password='wrongpass')
        self.assertIsNone(result)

    def test_no_request_duplicate_email_across_tenants_returns_none(self):
        other_tenant = make_tenant('nrbiz2')
        User.objects.create_user(email='dupe@shared.com', password='pass1234', tenant=self.tenant)
        User.objects.create_user(email='dupe@shared.com', password='pass1234', tenant=other_tenant)
        backend = TenantAwareModelBackend()
        result = backend.authenticate(None, username='dupe@shared.com', password='pass1234')
        self.assertIsNone(result)


class TenantAwareBackendWithRequestTests(TestCase):
    """Covers lines 50-51 (no candidates) and 69 (final failed check) of the
    request-scoped lookup path."""

    def setUp(self):
        self.tenant = make_tenant('wrbiz')

    def test_no_matching_email_returns_none(self):
        backend = TenantAwareModelBackend()
        request = SimpleNamespace(tenant=self.tenant)
        result = backend.authenticate(request, username='nobody@wrbiz.com', password='pass1234')
        self.assertIsNone(result)

    def test_wrong_password_with_request_returns_none(self):
        User.objects.create_user(email='u@wrbiz.com', password='pass1234', tenant=self.tenant)
        backend = TenantAwareModelBackend()
        request = SimpleNamespace(tenant=self.tenant)
        result = backend.authenticate(request, username='u@wrbiz.com', password='wrongpass')
        self.assertIsNone(result)

    def test_inactive_user_fails_user_can_authenticate(self):
        user = User.objects.create_user(email='inactive@wrbiz.com', password='pass1234', tenant=self.tenant)
        user.is_active = False
        user.save(update_fields=['is_active'])
        backend = TenantAwareModelBackend()
        request = SimpleNamespace(tenant=self.tenant)
        result = backend.authenticate(request, username='inactive@wrbiz.com', password='pass1234')
        self.assertIsNone(result)

    def test_correct_tenant_candidate_preferred_over_others(self):
        other_tenant = make_tenant('wrbiz2')
        User.objects.create_user(email='dupe@wrbiz.com', password='wrongone', tenant=other_tenant)
        User.objects.create_user(email='dupe@wrbiz.com', password='rightone', tenant=self.tenant)
        backend = TenantAwareModelBackend()
        request = SimpleNamespace(tenant=self.tenant)
        result = backend.authenticate(request, username='dupe@wrbiz.com', password='rightone')
        self.assertIsNotNone(result)
        self.assertEqual(result.tenant_id, self.tenant.id)

    def test_main_domain_prefers_platform_level_account(self):
        other_tenant = make_tenant('wrbiz3')
        User.objects.create_user(email='dupe2@platform.com', password='tenantpass', tenant=other_tenant)
        User.objects.create_user(email='dupe2@platform.com', password='platformpass', tenant=None)
        backend = TenantAwareModelBackend()
        request = SimpleNamespace(tenant=None)
        result = backend.authenticate(request, username='dupe2@platform.com', password='platformpass')
        self.assertIsNotNone(result)
        self.assertIsNone(result.tenant_id)

    def test_falls_back_to_first_candidate_when_no_exact_tenant_match(self):
        # No account exists on self.tenant, but one exists elsewhere with the
        # same email — the password check still runs against that candidate
        # so a view's own cross-tenant checks can produce a specific 403.
        other_tenant = make_tenant('wrbiz4')
        User.objects.create_user(email='elsewhere@x.com', password='pass1234', tenant=other_tenant)
        backend = TenantAwareModelBackend()
        request = SimpleNamespace(tenant=self.tenant)
        result = backend.authenticate(request, username='elsewhere@x.com', password='pass1234')
        self.assertIsNotNone(result)
        self.assertEqual(result.tenant_id, other_tenant.id)


class AccountsExtraCoverageTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(
            name='Test Business', slug='test', business_type='restaurant', plan='pro',
            is_active=True, onboarding_complete=True,
        )
        self.owner = User.objects.create_user(
            email='owner2@test.com', password='pass1234', tenant=self.tenant, role='owner',
        )
        self.customer = User.objects.create_user(
            email='cust@test.com', password='pass1234', tenant=self.tenant, role='customer',
        )
        self.client.defaults['HTTP_HOST'] = 'test.bizal.al'

    # ── Logout ────────────────────────────────────────────────

    def test_logout_success(self):
        refresh = RefreshToken.for_user(self.customer)
        self.client.force_authenticate(user=self.customer)
        resp = self.client.post('/api/auth/logout/', {'refresh': str(refresh)})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_logout_invalid_token(self):
        self.client.force_authenticate(user=self.customer)
        resp = self.client.post('/api/auth/logout/', {'refresh': 'not-a-real-token'})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_logout_missing_token(self):
        self.client.force_authenticate(user=self.customer)
        resp = self.client.post('/api/auth/logout/', {})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_logout_requires_auth(self):
        resp = self.client.post('/api/auth/logout/', {'refresh': 'x'})
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    # ── MeView ────────────────────────────────────────────────

    def test_me_get(self):
        self.client.force_authenticate(user=self.customer)
        resp = self.client.get('/api/auth/me/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['email'], 'cust@test.com')

    def test_me_patch_updates_profile(self):
        self.client.force_authenticate(user=self.customer)
        resp = self.client.patch('/api/auth/me/', {'full_name': 'New Name'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.full_name, 'New Name')

    def test_me_requires_auth(self):
        resp = self.client.get('/api/auth/me/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    # ── MeBookingsView ────────────────────────────────────────

    def test_me_bookings_empty(self):
        self.client.force_authenticate(user=self.customer)
        resp = self.client.get('/api/auth/me/bookings/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_me_bookings_filters_by_tenant_slug(self):
        from bookings.models import Booking
        Booking.objects.create(tenant=self.tenant, user=self.customer, booking_type='table',
                                guest_name='X', guest_phone='1', start_date='2026-08-01')
        self.client.force_authenticate(user=self.customer)
        resp = self.client.get('/api/auth/me/bookings/?tenant=test')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        resp2 = self.client.get('/api/auth/me/bookings/?tenant=nonexistent')
        self.assertEqual(resp2.status_code, status.HTTP_200_OK)

    # ── MeOrdersView ──────────────────────────────────────────

    def test_me_orders_empty(self):
        self.client.force_authenticate(user=self.customer)
        resp = self.client.get('/api/auth/me/orders/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_me_orders_filters_by_tenant(self):
        self.client.force_authenticate(user=self.customer)
        resp = self.client.get('/api/auth/me/orders/?tenant=test')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_me_orders_unexpected_error_returns_500(self):
        self.client.force_authenticate(user=self.customer)
        with patch('orders.models.Order.objects') as mock_mgr:
            mock_mgr.filter.side_effect = RuntimeError('boom')
            resp = self.client.get('/api/auth/me/orders/')
        self.assertEqual(resp.status_code, 500)

    # ── MeAppointmentsView ────────────────────────────────────

    def test_me_appointments_empty(self):
        self.client.force_authenticate(user=self.customer)
        resp = self.client.get('/api/auth/me/appointments/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_me_appointments_filters_by_tenant(self):
        self.client.force_authenticate(user=self.customer)
        resp = self.client.get('/api/auth/me/appointments/?tenant=test')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_me_appointments_unexpected_error_returns_500(self):
        self.client.force_authenticate(user=self.customer)
        with patch('appointments.models.Appointment.objects') as mock_mgr:
            mock_mgr.filter.side_effect = RuntimeError('boom')
            resp = self.client.get('/api/auth/me/appointments/')
        self.assertEqual(resp.status_code, 500)

    # ── MeReviewsView ─────────────────────────────────────────

    def test_me_reviews_empty(self):
        self.client.force_authenticate(user=self.customer)
        resp = self.client.get('/api/auth/me/reviews/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_me_reviews_returns_shaped_data(self):
        from reviews.models import Review
        Review.objects.create(tenant=self.tenant, user=self.customer, rating=5,
                               comment='Great place, would come back again!', is_approved=True)
        self.client.force_authenticate(user=self.customer)
        resp = self.client.get('/api/auth/me/reviews/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.data['results'] if isinstance(resp.data, dict) and 'results' in resp.data else resp.data
        self.assertEqual(data[0]['status'], 'approved')
        self.assertEqual(data[0]['tenant_name'], 'Test Business')

    def test_me_reviews_filters_by_tenant(self):
        self.client.force_authenticate(user=self.customer)
        resp = self.client.get('/api/auth/me/reviews/?tenant=test')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    # ── MeDeleteView ──────────────────────────────────────────

    def test_delete_account_success(self):
        self.client.force_authenticate(user=self.customer)
        resp = self.client.delete('/api/auth/me/delete/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.is_active)
        self.assertTrue(self.customer.email.startswith('deleted_'))
        self.assertEqual(self.customer.full_name, '')
        self.assertEqual(self.customer.notification_prefs, {})

    def test_delete_account_blacklists_outstanding_tokens(self):
        refresh = RefreshToken.for_user(self.customer)
        from rest_framework_simplejwt.token_blacklist.models import OutstandingToken, BlacklistedToken
        outstanding = OutstandingToken.objects.filter(user=self.customer).first()
        self.client.force_authenticate(user=self.customer)
        resp = self.client.delete('/api/auth/me/delete/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        if outstanding:
            self.assertTrue(BlacklistedToken.objects.filter(token=outstanding).exists())

    def test_delete_sole_owner_blocked(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.delete('/api/auth/me/delete/')
        self.assertEqual(resp.status_code, 400)
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.is_active)

    def test_delete_owner_allowed_when_other_owner_exists(self):
        User.objects.create_user(
            email='owner3@test.com', password='pass1234', tenant=self.tenant, role='owner',
        )
        self.client.force_authenticate(user=self.owner)
        resp = self.client.delete('/api/auth/me/delete/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_delete_account_deactivates_staff_member(self):
        from staff.models import StaffMember
        StaffMember.objects.create(tenant=self.tenant, user=self.customer, is_active=True)
        self.client.force_authenticate(user=self.customer)
        resp = self.client.delete('/api/auth/me/delete/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(StaffMember.objects.get(user=self.customer).is_active)

    def test_delete_requires_auth(self):
        resp = self.client.delete('/api/auth/me/delete/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    # ── MeNotificationPrefsView ───────────────────────────────

    def test_notification_prefs_get_default_empty(self):
        self.client.force_authenticate(user=self.customer)
        resp = self.client.get('/api/auth/me/notifications/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data, {})

    def test_notification_prefs_patch_valid(self):
        self.client.force_authenticate(user=self.customer)
        resp = self.client.patch('/api/auth/me/notifications/', {'booking': True, 'promo': False}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['booking'], True)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.notification_prefs['promo'], False)

    def test_notification_prefs_patch_merges_existing(self):
        self.customer.notification_prefs = {'booking': True}
        self.customer.save(update_fields=['notification_prefs'])
        self.client.force_authenticate(user=self.customer)
        resp = self.client.patch('/api/auth/me/notifications/', {'order': True}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data, {'booking': True, 'order': True})

    def test_notification_prefs_patch_unknown_key_rejected(self):
        self.client.force_authenticate(user=self.customer)
        resp = self.client.patch('/api/auth/me/notifications/', {'sms_spam': True}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_notification_prefs_patch_non_bool_value_rejected(self):
        self.client.force_authenticate(user=self.customer)
        resp = self.client.patch('/api/auth/me/notifications/', {'booking': 'yes'}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_notification_prefs_patch_too_many_keys_rejected(self):
        self.client.force_authenticate(user=self.customer)
        payload = {'booking': True, 'order': True, 'reminder': True, 'promo': True, 'news': True, 'extra': True}
        resp = self.client.patch('/api/auth/me/notifications/', payload, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_notification_prefs_patch_non_dict_body_rejected(self):
        self.client.force_authenticate(user=self.customer)
        resp = self.client.patch('/api/auth/me/notifications/', ['not', 'a', 'dict'], format='json')
        self.assertEqual(resp.status_code, 400)

    # ── EmailVerificationSendView ─────────────────────────────

    def test_verify_email_send_success(self):
        self.client.force_authenticate(user=self.customer)
        resp = self.client.post('/api/auth/verify-email/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_verify_email_send_already_verified(self):
        self.customer.is_email_verified = True
        self.customer.save(update_fields=['is_email_verified'])
        self.client.force_authenticate(user=self.customer)
        resp = self.client.post('/api/auth/verify-email/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('already verified', resp.data['detail'])

    def test_verify_email_send_smtp_failure_returns_502(self):
        self.client.force_authenticate(user=self.customer)
        with patch('accounts.views.send_mail', side_effect=Exception('smtp down')):
            resp = self.client.post('/api/auth/verify-email/')
        self.assertEqual(resp.status_code, 502)

    def test_verify_email_send_requires_auth(self):
        resp = self.client.post('/api/auth/verify-email/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    # ── EmailVerificationConfirmView edge cases ───────────────

    def test_verify_email_confirm_bad_uid(self):
        resp = self.client.get('/api/auth/verify-email/not-base64!!/sometoken/')
        self.assertEqual(resp.status_code, 400)

    def test_verify_email_confirm_nonexistent_user(self):
        import uuid as _uuid
        from django.utils.http import urlsafe_base64_encode
        from django.utils.encoding import force_bytes
        uid = urlsafe_base64_encode(force_bytes(str(_uuid.uuid4())))
        resp = self.client.get(f'/api/auth/verify-email/{uid}/sometoken/')
        self.assertEqual(resp.status_code, 400)

    def test_verify_email_confirm_inactive_user_rejected(self):
        from django.utils.http import urlsafe_base64_encode
        from django.utils.encoding import force_bytes
        from accounts.tokens import email_verification_token_generator
        self.customer.is_active = False
        self.customer.save(update_fields=['is_active'])
        uid = urlsafe_base64_encode(force_bytes(self.customer.pk))
        token = email_verification_token_generator.make_token(self.customer)
        resp = self.client.get(f'/api/auth/verify-email/{uid}/{token}/')
        self.assertEqual(resp.status_code, 400)

    # ── RegisterView email send failure is non-fatal ──────────

    def test_register_succeeds_even_if_verification_email_fails(self):
        with patch('accounts.views.send_mail', side_effect=Exception('smtp down')):
            resp = self.client.post('/api/auth/register/', {
                'email': 'resilient@test.com', 'password': 'securepass123',
            })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertIn('access', resp.data)

    # ── PasswordResetRequestView missing FRONTEND_BASE_URL fallback ──

    def test_password_reset_request_missing_frontend_base_url_falls_back(self):
        with patch('accounts.views.django_settings.FRONTEND_BASE_URL', ''):
            resp = self.client.post('/api/auth/password-reset/', {'email': 'owner2@test.com'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_password_reset_request_missing_email(self):
        resp = self.client.post('/api/auth/password-reset/', {})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    # ── PasswordResetConfirmView blacklists tokens ────────────

    def test_password_reset_confirm_blacklists_outstanding_tokens(self):
        from django.utils.http import urlsafe_base64_encode
        from django.utils.encoding import force_bytes
        from django.contrib.auth.tokens import default_token_generator
        from rest_framework_simplejwt.token_blacklist.models import OutstandingToken, BlacklistedToken
        refresh = RefreshToken.for_user(self.customer)
        outstanding = OutstandingToken.objects.filter(user=self.customer).first()
        uid = urlsafe_base64_encode(force_bytes(self.customer.pk))
        token = default_token_generator.make_token(self.customer)
        resp = self.client.post('/api/auth/password-reset/confirm/', {
            'uid': uid, 'token': token, 'new_password': 'brandnewpass987',
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        if outstanding:
            self.assertTrue(BlacklistedToken.objects.filter(token=outstanding).exists())

    # ── ChangePasswordView blacklists tokens ──────────────────

    def test_change_password_blacklists_outstanding_tokens(self):
        from rest_framework_simplejwt.token_blacklist.models import OutstandingToken, BlacklistedToken
        refresh = RefreshToken.for_user(self.customer)
        outstanding = OutstandingToken.objects.filter(user=self.customer).first()
        self.client.force_authenticate(user=self.customer)
        resp = self.client.post('/api/auth/change-password/', {
            'old_password': 'pass1234', 'new_password': 'newpassword987',
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        if outstanding:
            self.assertTrue(BlacklistedToken.objects.filter(token=outstanding).exists())

    # ── Login: onboarding-incomplete exception ────────────────

    def test_login_allowed_on_main_domain_when_onboarding_incomplete(self):
        incomplete_tenant = Tenant.objects.create(
            name='New Biz', slug='newbiz', business_type='shop', plan='free',
            is_active=True, onboarding_complete=False,
        )
        u = User.objects.create_user(
            email='newowner@test.com', password='pass1234',
            tenant=incomplete_tenant, role='owner',
        )
        self.client.defaults['HTTP_HOST'] = 'bizal.al'
        resp = self.client.post('/api/auth/login/', {
            'email': 'newowner@test.com', 'password': 'pass1234',
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


def make_tenant__final_gaps(slug, plan='pro'):
    return Tenant.objects.create(
        name=slug.title(), slug=slug, plan=plan, is_active=True, business_type='restaurant',
    )


class UserManagerGapsTest(TestCase):
    def test_create_user_requires_email(self):
        with self.assertRaises(ValueError):
            User.objects.create_user(email='', password='pass1234')

    def test_create_superuser_rejects_explicit_is_staff_false(self):
        with self.assertRaises(ValueError):
            User.objects.create_superuser(email='a@a.com', password='pass1234', is_staff=False)

    def test_create_superuser_rejects_explicit_is_superuser_false(self):
        with self.assertRaises(ValueError):
            User.objects.create_superuser(email='b@b.com', password='pass1234', is_superuser=False)

    def test_create_superuser_success(self):
        su = User.objects.create_superuser(email='root@root.com', password='pass1234')
        self.assertTrue(su.is_staff)
        self.assertTrue(su.is_superuser)
        self.assertEqual(su.role, 'superadmin')


class RegisterPasswordValidationTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant__final_gaps('registergap')
        self.client.defaults['HTTP_HOST'] = 'registergap.bizal.al'

    def test_common_password_rejected(self):
        resp = self.client.post('/api/auth/register/', {
            'email': 'newuser@registergap.com',
            'password': 'password',
            'full_name': 'New User',
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn('password', resp.data)


class StaffRoleTest(TestCase):
    def test_customer_has_no_staff_role(self):
        tenant = make_tenant__final_gaps('staffrolegap')
        user = User.objects.create_user(
            email='cust@staffrolegap.com', password='pass1234', tenant=tenant, role='customer',
        )
        client = APIClient()
        client.defaults['HTTP_HOST'] = 'staffrolegap.bizal.al'
        client.force_authenticate(user=user)
        resp = client.get('/api/auth/me/')
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.data['staff_role'])

    def test_active_staff_profile_returns_its_role(self):
        from staff.models import StaffMember
        tenant = make_tenant__final_gaps('staffroleactive')
        user = User.objects.create_user(
            email='staffer@staffroleactive.com', password='pass1234', tenant=tenant, role='staff',
        )
        StaffMember.objects.create(tenant=tenant, user=user, role='receptionist', is_active=True)
        client = APIClient()
        client.defaults['HTTP_HOST'] = 'staffroleactive.bizal.al'
        client.force_authenticate(user=user)
        resp = client.get('/api/auth/me/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['staff_role'], 'receptionist')


class MeSubResourceUnpaginatedBranchTest(TestCase):
    """
    _StandardPagination has a fixed page_size=20, so paginate_queryset()
    never actually returns None through real HTTP query params (DRF falls
    back to the fixed page_size on any invalid/zero page_size query value).
    The `page is not None` False branch in each Me*View is therefore only
    reachable by exercising it directly: patch paginate_queryset to return
    None the way DRF would if pagination were ever disabled for the view.
    """

    def setUp(self):
        self.tenant = make_tenant__final_gaps('mepagegap')
        self.user = User.objects.create_user(
            email='u@mepagegap.com', password='pass1234', tenant=self.tenant, role='customer',
        )
        self.client = APIClient()
        self.client.defaults['HTTP_HOST'] = 'mepagegap.bizal.al'
        self.client.force_authenticate(user=self.user)

    def test_me_bookings_unpaginated_response(self):
        with patch('accounts.views._StandardPagination.paginate_queryset', return_value=None):
            resp = self.client.get('/api/auth/me/bookings/')
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.data, list)

    def test_me_orders_unpaginated_response(self):
        with patch('accounts.views._StandardPagination.paginate_queryset', return_value=None):
            resp = self.client.get('/api/auth/me/orders/')
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.data, list)

    def test_me_reviews_unpaginated_response(self):
        with patch('accounts.views._StandardPagination.paginate_queryset', return_value=None):
            resp = self.client.get('/api/auth/me/reviews/')
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.data, list)

    def test_me_appointments_unpaginated_response(self):
        with patch('accounts.views._StandardPagination.paginate_queryset', return_value=None):
            resp = self.client.get('/api/auth/me/appointments/')
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.data, list)


class MeOrdersProgrammingErrorTest(TestCase):
    """MeOrdersView re-raises django.db.utils.ProgrammingError instead of
    swallowing it, so Django's exception middleware can alert operators."""

    def setUp(self):
        self.tenant = make_tenant__final_gaps('meordersgap')
        self.user = User.objects.create_user(
            email='u@meordersgap.com', password='pass1234', tenant=self.tenant, role='customer',
        )
        self.client = APIClient()
        self.client.defaults['HTTP_HOST'] = 'meordersgap.bizal.al'
        self.client.force_authenticate(user=self.user)

    def test_programming_error_is_reraised(self):
        from django.db.utils import ProgrammingError
        with patch('orders.models.Order.objects.filter', side_effect=ProgrammingError('missing column')):
            with self.assertRaises(ProgrammingError):
                self.client.get('/api/auth/me/orders/')


def _tiny_gif():
    return SimpleUploadedFile(
        'avatar.gif',
        b'GIF87a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;',
        content_type='image/gif',
    )


class ChangePasswordBlacklistTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(
            name='Gap Co', slug='gapco', business_type='restaurant', plan='pro', is_active=True,
        )
        self.owner = User.objects.create_user(
            email='owner@gapco.com', password='pass1234', tenant=self.tenant, role='owner',
        )

    def test_change_password_missing_fields_400(self):
        self.client.defaults['HTTP_HOST'] = 'gapco.bizal.al'
        self.client.force_authenticate(user=self.owner)
        resp = self.client.post('/api/auth/change-password/', {'old_password': 'pass1234'})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_change_password_blacklists_outstanding_tokens(self):
        RefreshToken.for_user(self.owner)
        self.client.defaults['HTTP_HOST'] = 'gapco.bizal.al'
        self.client.force_authenticate(user=self.owner)
        resp = self.client.post('/api/auth/change-password/', {
            'old_password': 'pass1234', 'new_password': 'newpass5678',
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_change_password_individual_token_blacklist_failure_logged(self):
        RefreshToken.for_user(self.owner)
        self.client.defaults['HTTP_HOST'] = 'gapco.bizal.al'
        self.client.force_authenticate(user=self.owner)
        with patch('rest_framework_simplejwt.tokens.RefreshToken.blacklist', side_effect=RuntimeError('boom')):
            resp = self.client.post('/api/auth/change-password/', {
                'old_password': 'pass1234', 'new_password': 'newpass5678',
            })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_change_password_revocation_outer_failure_logged(self):
        self.client.defaults['HTTP_HOST'] = 'gapco.bizal.al'
        self.client.force_authenticate(user=self.owner)
        with patch(
            'rest_framework_simplejwt.token_blacklist.models.OutstandingToken.objects.filter',
            side_effect=RuntimeError('db down'),
        ):
            resp = self.client.post('/api/auth/change-password/', {
                'old_password': 'pass1234', 'new_password': 'newpass5678',
            })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


class PasswordResetGapsTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(
            name='Gap Co', slug='gapco', business_type='restaurant', plan='pro', is_active=True,
        )
        self.owner = User.objects.create_user(
            email='owner@gapco.com', password='pass1234', tenant=self.tenant, role='owner',
        )

    def test_reset_request_email_send_failure_logged(self):
        with patch('accounts.views.send_mail', side_effect=RuntimeError('smtp down')):
            resp = self.client.post('/api/auth/password-reset/', {'email': 'owner@gapco.com'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_reset_confirm_missing_fields_400(self):
        resp = self.client.post('/api/auth/password-reset/confirm/', {'uid': 'x'})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def _valid_uid_token(self):
        from django.utils.http import urlsafe_base64_encode
        from django.utils.encoding import force_bytes
        from django.contrib.auth.tokens import default_token_generator
        uid = urlsafe_base64_encode(force_bytes(self.owner.pk))
        token = default_token_generator.make_token(self.owner)
        return uid, token

    def test_reset_confirm_blacklists_outstanding_tokens(self):
        RefreshToken.for_user(self.owner)
        uid, token = self._valid_uid_token()
        resp = self.client.post('/api/auth/password-reset/confirm/', {
            'uid': uid, 'token': token, 'new_password': 'brandnew5678',
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_reset_confirm_individual_token_blacklist_failure_logged(self):
        RefreshToken.for_user(self.owner)
        uid, token = self._valid_uid_token()
        with patch('rest_framework_simplejwt.tokens.RefreshToken.blacklist', side_effect=RuntimeError('boom')):
            resp = self.client.post('/api/auth/password-reset/confirm/', {
                'uid': uid, 'token': token, 'new_password': 'brandnew5678',
            })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_reset_confirm_revocation_outer_failure_logged(self):
        uid, token = self._valid_uid_token()
        with patch(
            'rest_framework_simplejwt.token_blacklist.models.OutstandingToken.objects.filter',
            side_effect=RuntimeError('db down'),
        ):
            resp = self.client.post('/api/auth/password-reset/confirm/', {
                'uid': uid, 'token': token, 'new_password': 'brandnew5678',
            })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


class MeSubResourceGapsTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(
            name='Gap Co', slug='gapco', business_type='restaurant', plan='pro', is_active=True,
        )
        self.owner = User.objects.create_user(
            email='owner@gapco.com', password='pass1234', tenant=self.tenant, role='owner',
        )
        self.client.defaults['HTTP_HOST'] = 'gapco.bizal.al'
        self.client.force_authenticate(user=self.owner)

    def test_me_orders_programming_error_reraises(self):
        from django.db.utils import ProgrammingError
        with patch('orders.models.Order.objects.filter', side_effect=ProgrammingError('no such column')):
            with self.assertRaises(ProgrammingError):
                self.client.get('/api/auth/me/orders/', **{'raise_request_exception': True})

    def test_me_orders_generic_exception_returns_500(self):
        with patch('orders.models.Order.objects.filter', side_effect=RuntimeError('boom')):
            resp = self.client.get('/api/auth/me/orders/')
        self.assertEqual(resp.status_code, 500)

    def test_me_orders_success_empty(self):
        resp = self.client.get('/api/auth/me/orders/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_me_appointments_programming_error_reraises(self):
        from django.db.utils import ProgrammingError
        with patch('appointments.models.Appointment.objects.filter', side_effect=ProgrammingError('no such column')):
            with self.assertRaises(ProgrammingError):
                self.client.get('/api/auth/me/appointments/', **{'raise_request_exception': True})

    def test_me_appointments_generic_exception_returns_500(self):
        with patch('appointments.models.Appointment.objects.filter', side_effect=RuntimeError('boom')):
            resp = self.client.get('/api/auth/me/appointments/')
        self.assertEqual(resp.status_code, 500)

    def test_me_appointments_success_empty(self):
        resp = self.client.get('/api/auth/me/appointments/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_me_reviews_success_empty(self):
        resp = self.client.get('/api/auth/me/reviews/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


class MeDeleteGapsTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(
            name='Gap Co', slug='gapco', business_type='restaurant', plan='pro', is_active=True,
        )
        self.owner = User.objects.create_user(
            email='owner@gapco.com', password='pass1234', tenant=self.tenant, role='owner',
        )
        # Second owner so the sole-owner guard doesn't block deletion
        User.objects.create_user(
            email='owner2@gapco.com', password='pass1234', tenant=self.tenant, role='owner',
        )
        self.client.defaults['HTTP_HOST'] = 'gapco.bizal.al'
        self.client.force_authenticate(user=self.owner)

    def test_delete_staffmember_lookup_failure_is_nonfatal(self):
        with patch('staff.models.StaffMember.objects.filter', side_effect=RuntimeError('boom')):
            resp = self.client.delete('/api/auth/me/delete/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_delete_removes_avatar_file(self):
        self.owner.avatar = _tiny_gif()
        self.owner.save()
        resp = self.client.delete('/api/auth/me/delete/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.owner.refresh_from_db()
        self.assertFalse(self.owner.avatar)

    def test_delete_blacklists_outstanding_tokens(self):
        RefreshToken.for_user(self.owner)
        resp = self.client.delete('/api/auth/me/delete/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_delete_individual_token_blacklist_failure_logged(self):
        RefreshToken.for_user(self.owner)
        with patch('rest_framework_simplejwt.tokens.RefreshToken.blacklist', side_effect=RuntimeError('boom')):
            resp = self.client.delete('/api/auth/me/delete/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_delete_revocation_outer_failure_logged(self):
        with patch(
            'rest_framework_simplejwt.token_blacklist.models.OutstandingToken.objects.filter',
            side_effect=RuntimeError('db down'),
        ):
            resp = self.client.delete('/api/auth/me/delete/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


class MeExportDataTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(
            name='Export Co', slug='exportco', business_type='restaurant', plan='pro', is_active=True,
        )
        self.other_tenant = Tenant.objects.create(
            name='Other Export Co', slug='otherexportco', business_type='restaurant', plan='pro', is_active=True,
        )
        self.user = User.objects.create_user(
            email='cust@exportco.com', password='pass1234', tenant=self.tenant, role='customer',
            full_name='Export Customer', phone='+35569000000', city='Tirana',
        )
        self.other_user = User.objects.create_user(
            email='other@exportco.com', password='pass1234', tenant=self.tenant, role='customer',
        )
        self.client.defaults['HTTP_HOST'] = 'exportco.bizal.al'
        self.client.force_authenticate(user=self.user)

    def test_unauthenticated_cannot_export(self):
        client = APIClient()
        client.defaults['HTTP_HOST'] = 'exportco.bizal.al'
        resp = client.get('/api/auth/me/export/')
        self.assertIn(resp.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_export_returns_profile(self):
        resp = self.client.get('/api/auth/me/export/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['profile']['email'], 'cust@exportco.com')
        self.assertEqual(resp.data['profile']['full_name'], 'Export Customer')
        self.assertEqual(resp.data['profile']['tenant'], 'exportco')

    def test_export_has_download_content_disposition(self):
        resp = self.client.get('/api/auth/me/export/')
        self.assertIn('attachment', resp['Content-Disposition'])
        self.assertIn(str(self.user.id), resp['Content-Disposition'])

    def test_export_includes_own_bookings_only(self):
        from bookings.models import Booking
        Booking.objects.create(
            tenant=self.tenant, user=self.user, booking_type='table', total_price='50.00',
        )
        Booking.objects.create(
            tenant=self.tenant, user=self.other_user, booking_type='table', total_price='999.00',
        )
        resp = self.client.get('/api/auth/me/export/')
        booking_prices = [b['total_price'] for b in resp.data['bookings']]
        self.assertIn('50.00', booking_prices)
        self.assertNotIn('999.00', booking_prices)

    def test_export_includes_own_reviews_only(self):
        from reviews.models import Review
        Review.objects.create(tenant=self.tenant, user=self.user, rating=5, comment='great')
        Review.objects.create(tenant=self.tenant, user=self.other_user, rating=1, comment='not mine')
        resp = self.client.get('/api/auth/me/export/')
        comments = [r['comment'] for r in resp.data['reviews']]
        self.assertIn('great', comments)
        self.assertNotIn('not mine', comments)

    def test_export_includes_own_payments_only(self):
        from payments.models import Payment
        Payment.objects.create(
            tenant=self.tenant, user=self.user, amount='120.00', payment_type='order', status='completed',
        )
        Payment.objects.create(
            tenant=self.tenant, user=self.other_user, amount='999.00', payment_type='order', status='completed',
        )
        resp = self.client.get('/api/auth/me/export/')
        amounts = [p['amount'] for p in resp.data['payments']]
        self.assertIn('120.00', amounts)
        self.assertNotIn('999.00', amounts)

    def test_export_empty_when_no_related_data(self):
        resp = self.client.get('/api/auth/me/export/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['bookings'], [])
        self.assertEqual(resp.data['orders'], [])
        self.assertEqual(resp.data['appointments'], [])
        self.assertEqual(resp.data['reviews'], [])
        self.assertEqual(resp.data['payments'], [])

    def test_orders_export_failure_is_nonfatal(self):
        with patch('orders.models.Order.objects.filter', side_effect=RuntimeError('boom')):
            resp = self.client.get('/api/auth/me/export/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['orders'], [])

    def test_appointments_export_failure_is_nonfatal(self):
        with patch('appointments.models.Appointment.objects.filter', side_effect=RuntimeError('boom')):
            resp = self.client.get('/api/auth/me/export/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['appointments'], [])

    def test_payments_export_failure_is_nonfatal(self):
        with patch('payments.models.Payment.objects.filter', side_effect=RuntimeError('boom')):
            resp = self.client.get('/api/auth/me/export/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['payments'], [])