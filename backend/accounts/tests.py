from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from accounts.models import User
from tenants.models import Tenant


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

    # ── Email verification (H-1: token generator separation) ────────────

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
        H-1 regression test: a token minted by default_token_generator
        (the password-reset generator) must NOT be accepted by
        EmailVerificationConfirmView. Before the fix, both flows shared
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
        H-1 regression test, opposite direction: a token minted by
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
