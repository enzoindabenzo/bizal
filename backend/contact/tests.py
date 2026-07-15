from unittest.mock import patch
from django.test import TestCase
from django.core import mail
from rest_framework.test import APIClient
from rest_framework import status
from accounts.models import User
from tenants.models import Tenant
from .models import ContactMessage, PlatformInquiry


def make_tenant(slug, plan='pro', active=True):
    return Tenant.objects.create(
        name=slug.title(), slug=slug, plan=plan,
        is_active=active, business_type='restaurant',
        email='owner@biznes.com',
    )


def make_user(email, tenant, role='owner'):
    return User.objects.create_user(
        email=email, password='pass1234', tenant=tenant, role=role,
    )


# ── Public contact form submission ────────────────────────────────────────────

class ContactSubmitTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('contactbiz')
        self.client.defaults['HTTP_HOST'] = 'contactbiz.bizal.al'

    def test_anyone_can_submit_message(self):
        resp = self.client.post('/api/contact/', {
            'name': 'Arben Hoxha',
            'email': 'arben@test.com',
            'message': 'I want to book a table for 4.',
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_message_saved_to_db(self):
        self.client.post('/api/contact/', {
            'name': 'Besmir Koci',
            'email': 'besmir@test.com',
            'message': 'Is the patio available?',
        })
        self.assertEqual(ContactMessage.objects.filter(tenant=self.tenant).count(), 1)
        msg = ContactMessage.objects.get(tenant=self.tenant)
        self.assertEqual(msg.name, 'Besmir Koci')
        self.assertFalse(msg.is_read)

    def test_email_sent_to_tenant(self):
        self.client.post('/api/contact/', {
            'name': 'Lira Gashi',
            'email': 'lira@test.com',
            'message': 'What are your hours?',
        })
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('owner@biznes.com', mail.outbox[0].to)

    def test_message_requires_name(self):
        resp = self.client.post('/api/contact/', {
            'email': 'test@test.com',
            'message': 'Hello',
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_message_requires_email(self):
        resp = self.client.post('/api/contact/', {
            'name': 'Test',
            'message': 'Hello',
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_message_requires_message_body(self):
        resp = self.client.post('/api/contact/', {
            'name': 'Test',
            'email': 'test@test.com',
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


# ── Owner admin: list / read messages ─────────────────────────────────────────

class ContactAdminTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('admincontact')
        self.other_tenant = make_tenant('othercontact')
        self.owner = make_user('owner@admincontact.com', self.tenant)
        self.customer = make_user('cust@admincontact.com', self.tenant, 'customer')
        self.client.defaults['HTTP_HOST'] = 'admincontact.bizal.al'

        ContactMessage.objects.create(
            tenant=self.tenant, name='Alpha', email='a@a.com', message='Hi',
        )
        ContactMessage.objects.create(
            tenant=self.other_tenant, name='Beta', email='b@b.com', message='Hidden',
        )

    def test_owner_can_list_messages(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.get('/api/contact/admin/messages/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        names = [m['name'] for m in ((resp.data['results'] if isinstance(resp.data, dict) else resp.data))]
        self.assertIn('Alpha', names)
        self.assertNotIn('Beta', names)

    def test_customer_cannot_list_messages(self):
        self.client.force_authenticate(user=self.customer)
        resp = self.client.get('/api/contact/admin/messages/')
        self.assertIn(resp.status_code, [
            status.HTTP_403_FORBIDDEN, status.HTTP_401_UNAUTHORIZED,
        ])

    def test_unauthenticated_cannot_list(self):
        resp = self.client.get('/api/contact/admin/messages/')
        self.assertIn(resp.status_code, [
            status.HTTP_403_FORBIDDEN, status.HTTP_401_UNAUTHORIZED,
        ])

    def test_reading_a_message_marks_it_read(self):
        msg = ContactMessage.objects.get(tenant=self.tenant)
        self.client.force_authenticate(user=self.owner)
        resp = self.client.patch(
            f'/api/contact/admin/messages/{msg.pk}/', {'is_read': True}
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        msg.refresh_from_db()
        self.assertTrue(msg.is_read)


# ── Contact reply ─────────────────────────────────────────────────────────────

class ContactReplyTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('replybiz')
        self.owner = make_user('owner@replybiz.com', self.tenant)
        self.client.defaults['HTTP_HOST'] = 'replybiz.bizal.al'
        self.msg = ContactMessage.objects.create(
            tenant=self.tenant, name='Customer X',
            email='customerx@test.com', message='Original message',
        )

    def test_owner_can_reply(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.post(
            f'/api/contact/admin/messages/{self.msg.pk}/reply/',
            {'reply': 'Thank you for contacting us!'},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_reply_sends_email_to_sender(self):
        self.client.force_authenticate(user=self.owner)
        self.client.post(
            f'/api/contact/admin/messages/{self.msg.pk}/reply/',
            {'reply': 'We will get back to you.'},
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('customerx@test.com', mail.outbox[0].to)

    def test_reply_sets_replied_at(self):
        self.client.force_authenticate(user=self.owner)
        self.client.post(
            f'/api/contact/admin/messages/{self.msg.pk}/reply/',
            {'reply': 'Reply text here.'},
        )
        self.msg.refresh_from_db()
        self.assertIsNotNone(self.msg.replied_at)

    def test_empty_reply_rejected(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.post(
            f'/api/contact/admin/messages/{self.msg.pk}/reply/',
            {'reply': ''},
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_wrong_tenant_cannot_reply(self):
        other_tenant = make_tenant('wrongreply')
        other_owner = make_user('owner@wrongreply.com', other_tenant)
        self.client.force_authenticate(user=other_owner)
        resp = self.client.post(
            f'/api/contact/admin/messages/{self.msg.pk}/reply/',
            {'reply': 'Hack attempt'},
        )
        # IsTenantOwner rejects before the lookup even happens, since
        # other_owner doesn't belong to self.tenant (the host's tenant).
        self.assertIn(resp.status_code, [
            status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND,
        ])


class ContactNotifyAsyncTest(TestCase):
    """Submitting a contact form must dispatch notify_owner_async.delay,
    not call notify_owner synchronously on the request thread."""

    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('asynccontact')
        self.client.defaults['HTTP_HOST'] = 'asynccontact.bizal.al'

    @patch('contact.views.notify_owner_async')
    def test_contact_submit_dispatches_async_notification(self, mock_task):
        resp = self.client.post('/api/contact/', {
            'name': 'Test User', 'email': 'test@example.com',
            'message': 'Hello there',
        })
        self.assertEqual(resp.status_code, 201, resp.data)
        mock_task.delay.assert_called_once()
        args = mock_task.delay.call_args[0]
        self.assertEqual(args[0], str(self.tenant.pk))
        self.assertEqual(args[1], 'new_contact')

    @patch('contact.views.notify_owner_async')
    def test_sync_notify_owner_not_called_on_contact_submit(self, mock_task):
        with patch('notifications.utils.notify_owner') as mock_sync:
            self.client.post('/api/contact/', {
                'name': 'Test User', 'email': 'test@example.com',
                'message': 'Hello',
            })
            mock_sync.assert_not_called()


# ── Platform-level contact submission (main domain, no tenant) ───────────────

class PlatformContactSubmitTest(TestCase):
    """The marketing site (bizal.al) has no tenant context, so its contact
    form must not depend on TenantDomainOnly / a tenant FK."""

    def setUp(self):
        self.client = APIClient()
        self.client.defaults['HTTP_HOST'] = 'bizal.al'

    def test_anyone_can_submit_platform_inquiry(self):
        resp = self.client.post('/api/contact/platform/', {
            'name': 'Arben Hoxha',
            'email': 'arben@example.com',
            'subject': '[Pricing] Question',
            'message': 'How much does the Pro plan cost?',
        })
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(PlatformInquiry.objects.count(), 1)
        inquiry = PlatformInquiry.objects.first()
        self.assertEqual(inquiry.email, 'arben@example.com')

    def test_missing_required_fields_rejected(self):
        resp = self.client.post('/api/contact/platform/', {'name': 'No Email'})
        self.assertEqual(resp.status_code, 400)

    def test_sends_email_to_admin(self):
        resp = self.client.post('/api/contact/platform/', {
            'name': 'Test User', 'email': 'test@example.com',
            'message': 'Interested in a demo.',
        })
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(len(mail.outbox), 1)
