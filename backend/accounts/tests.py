from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from tenants.models import Tenant, PLAN_PRO
from .models import User


def make_tenant(slug='test', active=True):
    return Tenant.objects.create(name='Test', slug=slug, plan=PLAN_PRO, is_active=active)


class RegisterTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant()

    def test_register_on_tenant(self):
        self.client.defaults['HTTP_HOST'] = 'test.bizal.al'
        resp = self.client.post('/api/auth/register/', {
            'email': 'user@test.com', 'password': 'securepass123', 'full_name': 'Test User'
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(email='user@test.com')
        self.assertEqual(user.tenant, self.tenant)
        self.assertEqual(user.role, 'customer')

    def test_register_duplicate_email(self):
        User.objects.create_user(email='dup@test.com', password='pass1234')
        self.client.defaults['HTTP_HOST'] = 'test.bizal.al'
        resp = self.client.post('/api/auth/register/', {
            'email': 'dup@test.com', 'password': 'securepass123'
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class LoginTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant(slug='hertz')
        self.other_tenant = make_tenant(slug='gears')
        self.user = User.objects.create_user(
            email='owner@hertz.com', password='pass1234',
            tenant=self.tenant, role='owner'
        )

    def test_login_returns_tokens(self):
        self.client.defaults['HTTP_HOST'] = 'hertz.bizal.al'
        resp = self.client.post('/api/auth/login/', {'email': 'owner@hertz.com', 'password': 'pass1234'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('access', resp.data)
        self.assertIn('refresh', resp.data)

    def test_cross_tenant_login_rejected(self):
        self.client.defaults['HTTP_HOST'] = 'gears.bizal.al'
        resp = self.client.post('/api/auth/login/', {'email': 'owner@hertz.com', 'password': 'pass1234'})
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_non_staff_cannot_login_main_domain(self):
        self.client.defaults['HTTP_HOST'] = 'bizal.al'
        resp = self.client.post('/api/auth/login/', {'email': 'owner@hertz.com', 'password': 'pass1234'})
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


class AccountsAppConfig(TestCase):
    def test_app_name(self):
        from accounts.apps import AccountsConfig
        self.assertEqual(AccountsConfig.name, 'accounts')
