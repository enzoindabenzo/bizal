from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from accounts.models import User
from tenants.models import Tenant, PLAN_ENTERPRISE, PLAN_TRIAL


def make_tenant(slug='bizbot-biz', **kwargs):
    defaults = dict(
        name='Test Biz', slug=slug, business_type='restaurant',
        plan=PLAN_ENTERPRISE, is_active=True,
    )
    defaults.update(kwargs)
    return Tenant.objects.create(**defaults)


def make_user(email, tenant=None, role='customer', **kwargs):
    return User.objects.create_user(
        email=email, password='pass1234', tenant=tenant, role=role, **kwargs
    )


def expired_bearer_header(user):
    """A syntactically valid JWT for `user` whose exp claim is already in the past."""
    token = AccessToken.for_user(user)
    token.set_exp(lifetime=timedelta(seconds=-1))
    return f'Bearer {token}'


class ChatbotAuthGateTests(TestCase):
    """
    Covers the auth gate added to chat/handoff/poll: anonymous visitors must be
    rejected, authenticated visitors must be let through, expired/malformed
    tokens must be rejected the same as missing ones, and none of this should
    differ between the main domain and a tenant subdomain.
    """

    def setUp(self):
        self.tenant = make_tenant()
        self.user = make_user('visitor@example.com', tenant=self.tenant)
        self.client = APIClient()

    # ── chat() — main domain, no tenant_slug ────────────────────────────────

    def test_chat_anonymous_rejected_main_domain(self):
        resp = self.client.post('/api/chatbot/chat/', {
            'messages': [{'role': 'user', 'content': 'hello'}],
        }, format='json')
        self.assertEqual(resp.status_code, 401)

    @patch('chatbot.views._rotate_call', return_value=('Hi there!', 'groq_1', False))
    def test_chat_authenticated_allowed_main_domain(self, mock_rotate):
        self.client.force_authenticate(user=self.user)
        resp = self.client.post('/api/chatbot/chat/', {
            'messages': [{'role': 'user', 'content': 'What plans do you have?'}],
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.data if hasattr(resp, 'data') else resp.content)
        self.assertEqual(resp.json()['reply'], 'Hi there!')
        mock_rotate.assert_called_once()

    def test_chat_expired_token_rejected_main_domain(self):
        self.client.credentials(HTTP_AUTHORIZATION=expired_bearer_header(self.user))
        resp = self.client.post('/api/chatbot/chat/', {
            'messages': [{'role': 'user', 'content': 'hello'}],
        }, format='json')
        self.assertEqual(resp.status_code, 401)

    def test_chat_malformed_token_rejected_main_domain(self):
        self.client.credentials(HTTP_AUTHORIZATION='Bearer not-a-real-token')
        resp = self.client.post('/api/chatbot/chat/', {
            'messages': [{'role': 'user', 'content': 'hello'}],
        }, format='json')
        self.assertEqual(resp.status_code, 401)

    # ── chat() — tenant subdomain ────────────────────────────────────────────

    def test_chat_anonymous_rejected_on_tenant_subdomain(self):
        self.client.defaults['HTTP_HOST'] = f'{self.tenant.slug}.bizal.al'
        resp = self.client.post('/api/chatbot/chat/', {
            'messages': [{'role': 'user', 'content': 'hello'}],
            'tenant_slug': self.tenant.slug,
        }, format='json')
        self.assertEqual(resp.status_code, 401)

    @patch('chatbot.views._rotate_call', return_value=('We are open 9-5.', 'groq_1', False))
    def test_chat_authenticated_allowed_on_tenant_subdomain(self, mock_rotate):
        self.client.defaults['HTTP_HOST'] = f'{self.tenant.slug}.bizal.al'
        self.client.force_authenticate(user=self.user)
        resp = self.client.post('/api/chatbot/chat/', {
            'messages': [{'role': 'user', 'content': 'What are your hours?'}],
            'tenant_slug': self.tenant.slug,
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.data if hasattr(resp, 'data') else resp.content)
        mock_rotate.assert_called_once()

    def test_chat_expired_token_rejected_on_tenant_subdomain(self):
        self.client.defaults['HTTP_HOST'] = f'{self.tenant.slug}.bizal.al'
        self.client.credentials(HTTP_AUTHORIZATION=expired_bearer_header(self.user))
        resp = self.client.post('/api/chatbot/chat/', {
            'messages': [{'role': 'user', 'content': 'hello'}],
            'tenant_slug': self.tenant.slug,
        }, format='json')
        self.assertEqual(resp.status_code, 401)

    # A trial (non-Enterprise) tenant should still 401 an anonymous caller
    # before the plan check is ever reached — auth is checked first.
    def test_chat_anonymous_rejected_even_for_non_enterprise_tenant(self):
        trial_tenant = make_tenant(slug='trial-biz', plan=PLAN_TRIAL)
        self.client.defaults['HTTP_HOST'] = f'{trial_tenant.slug}.bizal.al'
        resp = self.client.post('/api/chatbot/chat/', {
            'messages': [{'role': 'user', 'content': 'hello'}],
            'tenant_slug': trial_tenant.slug,
        }, format='json')
        self.assertEqual(resp.status_code, 401)

    # ── handoff() ────────────────────────────────────────────────────────────

    def test_handoff_anonymous_rejected(self):
        resp = self.client.post('/api/chatbot/handoff/', {
            'tenant_slug': self.tenant.slug,
            'session_id': 'whatever',
        }, format='json')
        self.assertEqual(resp.status_code, 401)

    def test_handoff_authenticated_allowed(self):
        self.client.force_authenticate(user=self.user)
        from chatbot.views import _make_session_token
        session_token = _make_session_token('11111111-1111-1111-1111-111111111111')
        resp = self.client.post('/api/chatbot/handoff/', {
            'tenant_slug': self.tenant.slug,
            'session_id': session_token,
            'visitor_name': 'Ana',
            'summary': 'Wants to book a table.',
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.data if hasattr(resp, 'data') else resp.content)

    def test_handoff_expired_token_rejected(self):
        self.client.credentials(HTTP_AUTHORIZATION=expired_bearer_header(self.user))
        resp = self.client.post('/api/chatbot/handoff/', {
            'tenant_slug': self.tenant.slug,
            'session_id': 'whatever',
        }, format='json')
        self.assertEqual(resp.status_code, 401)

    def test_handoff_anonymous_rejected_on_tenant_subdomain(self):
        self.client.defaults['HTTP_HOST'] = f'{self.tenant.slug}.bizal.al'
        resp = self.client.post('/api/chatbot/handoff/', {
            'tenant_slug': self.tenant.slug,
            'session_id': 'whatever',
        }, format='json')
        self.assertEqual(resp.status_code, 401)

    # ── poll() ───────────────────────────────────────────────────────────────

    def test_poll_anonymous_rejected(self):
        resp = self.client.get('/api/chatbot/poll/some-session-id/')
        self.assertEqual(resp.status_code, 401)

    def test_poll_authenticated_allowed(self):
        self.client.force_authenticate(user=self.user)
        from chatbot.views import _make_session_token
        session_token = _make_session_token('22222222-2222-2222-2222-222222222222')
        resp = self.client.get(f'/api/chatbot/poll/{session_token}/')
        self.assertEqual(resp.status_code, 200, resp.data if hasattr(resp, 'data') else resp.content)
        self.assertIn('staff_reply', resp.json())

    def test_poll_expired_token_rejected(self):
        self.client.credentials(HTTP_AUTHORIZATION=expired_bearer_header(self.user))
        resp = self.client.get('/api/chatbot/poll/some-session-id/')
        self.assertEqual(resp.status_code, 401)

    def test_poll_anonymous_rejected_on_tenant_subdomain(self):
        self.client.defaults['HTTP_HOST'] = f'{self.tenant.slug}.bizal.al'
        resp = self.client.get('/api/chatbot/poll/some-session-id/')
        self.assertEqual(resp.status_code, 401)

    # ── staff_reply() — already role-gated, confirm the base auth layer too ──

    def test_staff_reply_anonymous_rejected(self):
        resp = self.client.post('/api/chatbot/staff-reply/', {
            'tenant_slug': self.tenant.slug,
            'session_id': 'whatever',
            'message': 'hi',
        }, format='json')
        self.assertEqual(resp.status_code, 401)

    def test_staff_reply_expired_token_rejected(self):
        self.client.credentials(HTTP_AUTHORIZATION=expired_bearer_header(self.user))
        resp = self.client.post('/api/chatbot/staff-reply/', {
            'tenant_slug': self.tenant.slug,
            'session_id': 'whatever',
            'message': 'hi',
        }, format='json')
        self.assertEqual(resp.status_code, 401)
