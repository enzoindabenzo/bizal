import json
import datetime
from decimal import Decimal
from unittest.mock import patch, MagicMock
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from accounts.models import User
from tenants.models import Tenant
from bookings.models import Booking
from .models import Payment


def make_tenant(slug, plan='enterprise', active=True, accepts_online_payments=True):
    return Tenant.objects.create(
        name=slug.title(), slug=slug, plan=plan,
        is_active=active, business_type='car_rental',
        accepts_online_payments=accepts_online_payments,
    )


def make_user(email, tenant, role='owner'):
    return User.objects.create_user(
        email=email, password='pass1234', tenant=tenant, role=role,
    )


# ── Model tests ───────────────────────────────────────────────────────────────

class PaymentModelTest(TestCase):
    def setUp(self):
        self.tenant = make_tenant('paybiz')
        self.user = make_user('user@paybiz.com', self.tenant)

    def test_str(self):
        p = Payment.objects.create(
            tenant=self.tenant, user=self.user,
            amount=5000, payment_type='invoice', status='completed',
        )
        s = str(p)
        self.assertIn('paybiz', s)
        self.assertIn('invoice', s)

    def test_defaults_to_pending(self):
        p = Payment.objects.create(
            tenant=self.tenant, user=self.user,
            amount=1000, payment_type='order',
        )
        self.assertEqual(p.status, 'pending')

    def test_currency_defaults_to_ALL(self):
        p = Payment.objects.create(
            tenant=self.tenant, user=self.user,
            amount=3000, payment_type='subscription',
        )
        self.assertEqual(p.currency, 'ALL')


# ── Payment list API ──────────────────────────────────────────────────────────

class PaymentListAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('listpaybiz')
        self.other_tenant = make_tenant('otherpaybiz')
        self.owner = make_user('owner@listpaybiz.com', self.tenant)
        self.customer = make_user('cust@listpaybiz.com', self.tenant, 'customer')
        self.client.defaults['HTTP_HOST'] = 'listpaybiz.bizal.al'

        Payment.objects.create(
            tenant=self.tenant, amount=2000,
            payment_type='invoice', status='completed',
        )
        Payment.objects.create(
            tenant=self.tenant, amount=500,
            payment_type='order', status='pending',
        )
        Payment.objects.create(
            tenant=self.other_tenant, amount=9999,
            payment_type='invoice', status='completed',
        )

    def test_owner_can_list_payments(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.get('/api/payments/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        amounts = [float(p['amount']) for p in ((resp.data['results'] if isinstance(resp.data, dict) else resp.data))]
        self.assertIn(2000.0, amounts)
        self.assertIn(500.0, amounts)
        self.assertNotIn(9999.0, amounts)   # other tenant — must not leak

    def test_customer_cannot_list_payments(self):
        self.client.force_authenticate(user=self.customer)
        resp = self.client.get('/api/payments/')
        self.assertIn(resp.status_code, [
            status.HTTP_403_FORBIDDEN, status.HTTP_401_UNAUTHORIZED,
        ])

    def test_unauthenticated_cannot_list(self):
        resp = self.client.get('/api/payments/')
        self.assertIn(resp.status_code, [
            status.HTTP_403_FORBIDDEN, status.HTTP_401_UNAUTHORIZED,
        ])

    def test_filter_by_status(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.get('/api/payments/?status=completed')
        amounts = [float(p['amount']) for p in ((resp.data['results'] if isinstance(resp.data, dict) else resp.data))]
        self.assertIn(2000.0, amounts)
        self.assertNotIn(500.0, amounts)


# ── Stripe subscribe endpoint ─────────────────────────────────────────────────

class StripeSubscribeTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('stripebiz')
        self.owner = make_user('owner@stripebiz.com', self.tenant)
        self.client.defaults['HTTP_HOST'] = 'stripebiz.bizal.al'
        self.client.force_authenticate(user=self.owner)

    @patch('payments.views.stripe.checkout.Session.create')
    def test_subscribe_pro_returns_checkout_url(self, mock_create):
        mock_create.return_value = MagicMock(url='https://checkout.stripe.com/test')
        resp = self.client.post('/api/payments/subscribe/', {'plan': 'pro'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('checkout_url', resp.data)
        self.assertEqual(resp.data['checkout_url'], 'https://checkout.stripe.com/test')

    @patch('payments.views.stripe.checkout.Session.create')
    def test_subscribe_enterprise_returns_checkout_url(self, mock_create):
        mock_create.return_value = MagicMock(url='https://checkout.stripe.com/ent')
        resp = self.client.post('/api/payments/subscribe/', {'plan': 'enterprise'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_subscribe_invalid_plan_rejected(self):
        resp = self.client.post('/api/payments/subscribe/', {'plan': 'bogus'})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unauthenticated_cannot_subscribe(self):
        self.client.logout()
        resp = self.client.post('/api/payments/subscribe/', {'plan': 'pro'})
        self.assertIn(resp.status_code, [
            status.HTTP_403_FORBIDDEN, status.HTTP_401_UNAUTHORIZED,
        ])


# ── Stripe webhook ────────────────────────────────────────────────────────────

class StripeWebhookTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('webhookbiz', active=False)
        self.client.defaults['HTTP_HOST'] = 'webhookbiz.bizal.al'

    @patch('payments.views.stripe.Webhook.construct_event')
    def test_checkout_session_completed_activates_tenant(self, mock_event):
        mock_event.return_value = {
            'id': 'evt_checkout_001',   # required by idempotency cache (event["id"])
            'type': 'checkout.session.completed',
            'data': {
                'object': {
                    'metadata': {'tenant_slug': 'webhookbiz', 'plan': 'pro'},
                    'subscription': 'sub_test123',
                    'customer': 'cus_test456',
                }
            }
        }
        resp = self.client.post(
            '/api/payments/webhook/',
            data=json.dumps({}),
            content_type='application/json',
            HTTP_STRIPE_SIGNATURE='test_sig',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.tenant.refresh_from_db()
        self.assertTrue(self.tenant.is_active)
        self.assertEqual(self.tenant.plan, 'pro')
        self.assertEqual(self.tenant.stripe_subscription_id, 'sub_test123')

    @patch('payments.views.stripe.Webhook.construct_event')
    def test_subscription_deleted_downgrades_tenant(self, mock_event):
        self.tenant.is_active = True
        self.tenant.stripe_subscription_id = 'sub_del123'
        self.tenant.save()
        mock_event.return_value = {
            'id': 'evt_del_001',   # required by idempotency cache (event["id"])
            'type': 'customer.subscription.deleted',
            'data': {'object': {'id': 'sub_del123'}},
        }
        resp = self.client.post(
            '/api/payments/webhook/',
            data=json.dumps({}),
            content_type='application/json',
            HTTP_STRIPE_SIGNATURE='test_sig',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.tenant.refresh_from_db()
        self.assertFalse(self.tenant.is_active)
        self.assertEqual(self.tenant.plan, 'starter')

    def test_invalid_signature_rejected(self):
        with patch('payments.views.stripe.Webhook.construct_event', side_effect=Exception('bad sig')):
            resp = self.client.post(
                '/api/payments/webhook/',
                data=json.dumps({}),
                content_type='application/json',
                HTTP_STRIPE_SIGNATURE='invalid',
            )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


# ── Webhook: customer.subscription.updated ───────────────────────────────────

class StripeWebhookSubscriptionUpdatedTest(TestCase):
    """
    _handle_event branches on customer.subscription.updated — the plan-upgrade
    logic and is_active flip were previously untested.
    """

    def setUp(self):
        self.client = APIClient()
        self.client.defaults['HTTP_HOST'] = 'webhookbiz2.bizal.al'
        self.tenant = Tenant.objects.create(
            name='Webhookbiz2', slug='webhookbiz2', plan='starter',
            is_active=True, business_type='car_rental',
            stripe_subscription_id='sub_upd123',
        )

    def _post_event(self, event_dict):
        with patch('payments.views.stripe.Webhook.construct_event', return_value=event_dict):
            return self.client.post(
                '/api/payments/webhook/',
                data=json.dumps({}),
                content_type='application/json',
                HTTP_STRIPE_SIGNATURE='test_sig',
            )

    @patch('payments.views._plan_price_map', return_value={'pro': 'price_pro_test', 'enterprise': 'price_ent_test'})
    def test_active_subscription_with_recognized_price_upgrades_plan(self, _mock):
        resp = self._post_event({
            'id': 'evt_upd_001',
            'type': 'customer.subscription.updated',
            'data': {'object': {
                'id': 'sub_upd123',
                'status': 'active',
                'items': {'data': [{'price': {'id': 'price_pro_test'}}]},
            }},
        })
        self.assertEqual(resp.status_code, 200)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.plan, 'pro')
        self.assertTrue(self.tenant.is_active)

    @patch('payments.views._plan_price_map', return_value={'pro': 'price_pro_test', 'enterprise': 'price_ent_test'})
    def test_unrecognized_price_id_does_not_change_plan(self, _mock):
        """Unknown Stripe price IDs should leave the plan unchanged but still set is_active."""
        resp = self._post_event({
            'id': 'evt_upd_002',
            'type': 'customer.subscription.updated',
            'data': {'object': {
                'id': 'sub_upd123',
                'status': 'active',
                'items': {'data': [{'price': {'id': 'price_unknown'}}]},
            }},
        })
        self.assertEqual(resp.status_code, 200)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.plan, 'starter')  # unchanged
        self.assertTrue(self.tenant.is_active)

    @patch('payments.views._plan_price_map', return_value={'pro': 'price_pro_test', 'enterprise': 'price_ent_test'})
    def test_past_due_status_does_not_activate_tenant(self, _mock):
        """Only 'active'/'trialing' statuses should flip is_active — past_due must not."""
        self.tenant.is_active = False
        self.tenant.save(update_fields=['is_active'])
        resp = self._post_event({
            'id': 'evt_upd_003',
            'type': 'customer.subscription.updated',
            'data': {'object': {
                'id': 'sub_upd123',
                'status': 'past_due',
                'items': {'data': [{'price': {'id': 'price_pro_test'}}]},
            }},
        })
        self.assertEqual(resp.status_code, 200)
        self.tenant.refresh_from_db()
        self.assertFalse(self.tenant.is_active)  # must stay inactive

    def test_unknown_subscription_id_is_silently_skipped(self):
        resp = self._post_event({
            'id': 'evt_upd_004',
            'type': 'customer.subscription.updated',
            'data': {'object': {
                'id': 'sub_DOESNOTEXIST',
                'status': 'active',
                'items': {'data': []},
            }},
        })
        self.assertEqual(resp.status_code, 200)  # must not raise 400


# ── Webhook: invoice.payment_failed ──────────────────────────────────────────

class StripeWebhookPaymentFailedTest(TestCase):
    """
    invoice.payment_failed sends an email to the tenant owner and clears cache.
    Previously zero tests covered this branch.
    """

    def setUp(self):
        self.client = APIClient()
        self.client.defaults['HTTP_HOST'] = 'failbiz.bizal.al'
        self.tenant = Tenant.objects.create(
            name='Failbiz', slug='failbiz', plan='pro',
            is_active=True, business_type='car_rental',
            stripe_subscription_id='sub_fail123',
        )
        self.owner = User.objects.create_user(
            email='owner@failbiz.com', password='pass1234',
            tenant=self.tenant, role='owner',
        )

    def _post_event(self, event_dict):
        with patch('payments.views.stripe.Webhook.construct_event', return_value=event_dict):
            return self.client.post(
                '/api/payments/webhook/',
                data=json.dumps({}),
                content_type='application/json',
                HTTP_STRIPE_SIGNATURE='test_sig',
            )

    def test_payment_failed_sends_email_to_owner(self):
        from django.core import mail
        resp = self._post_event({
            'id': 'evt_fail_001',
            'type': 'invoice.payment_failed',
            'data': {'object': {'subscription': 'sub_fail123'}},
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.owner.email, mail.outbox[0].recipients())
        self.assertIn('dështoi', mail.outbox[0].subject)  # Albanian "failed"

    def test_payment_failed_with_no_owner_does_not_crash(self):
        """If the tenant has no owner user, _notify_payment_failed must not raise."""
        self.owner.delete()
        resp = self._post_event({
            'id': 'evt_fail_002',
            'type': 'invoice.payment_failed',
            'data': {'object': {'subscription': 'sub_fail123'}},
        })
        self.assertEqual(resp.status_code, 200)


# ── Webhook: idempotency ──────────────────────────────────────────────────────

class StripeWebhookIdempotencyTest(TestCase):
    """Duplicate Stripe event IDs must be skipped (cache guard)."""

    def setUp(self):
        self.client = APIClient()
        self.client.defaults['HTTP_HOST'] = 'idembiz.bizal.al'
        self.tenant = Tenant.objects.create(
            name='Idembiz', slug='idembiz', plan='starter',
            is_active=False, business_type='car_rental',
        )

    def test_duplicate_event_is_processed_only_once(self):
        event = {
            'id': 'evt_idem_001',
            'type': 'checkout.session.completed',
            'data': {'object': {
                'metadata': {'tenant_slug': 'idembiz', 'plan': 'pro'},
                'subscription': 'sub_idem',
                'customer': 'cus_idem',
            }},
        }
        # DummyCache (used globally in tests) always misses, which defeats the
        # idempotency guard. Override to LocMemCache just for this test so the
        # cache.set() in the webhook view persists within the test process.
        from django.core.cache.backends.locmem import LocMemCache
        real_cache = LocMemCache('idempotency-test', {})
        real_cache.clear()
        with patch('payments.views.cache', real_cache):
            with patch('payments.views.stripe.Webhook.construct_event', return_value=event):
                r1 = self.client.post('/api/payments/webhook/', data=json.dumps({}),
                                      content_type='application/json', HTTP_STRIPE_SIGNATURE='sig')
                r2 = self.client.post('/api/payments/webhook/', data=json.dumps({}),
                                      content_type='application/json', HTTP_STRIPE_SIGNATURE='sig')
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.assertIn('duplicate', r2.data.get('status', ''))
        # The tenant should have been activated exactly once (first call)
        self.tenant.refresh_from_db()
        self.assertTrue(self.tenant.is_active)


# ── Booking deposit checkout ─────────────────────────────────────────────────

def make_booking(tenant, user=None, total_price='500.00', deposit_paid='0.00', status='pending'):
    return Booking.objects.create(
        tenant=tenant, user=user, booking_type='rental', status=status,
        start_date=datetime.date(2026, 9, 1), end_date=datetime.date(2026, 9, 3),
        total_price=Decimal(total_price), deposit_paid=Decimal(deposit_paid),
        guest_name='Guest', guest_email='guest@test.com',
    )


class BookingCheckoutTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('depositbiz')
        self.owner = make_user('owner@depositbiz.com', self.tenant)
        self.customer = make_user('cust@depositbiz.com', self.tenant, role='customer')
        self.other_customer = make_user('other@depositbiz.com', self.tenant, role='customer')
        self.client.defaults['HTTP_HOST'] = 'depositbiz.bizal.al'

    @patch('payments.views.stripe.checkout.Session.create')
    def test_customer_can_pay_own_booking(self, mock_create):
        mock_create.return_value = MagicMock(url='https://checkout.stripe.com/deposit')
        booking = make_booking(self.tenant, user=self.customer)
        self.client.force_authenticate(user=self.customer)
        resp = self.client.post(f'/api/payments/booking/{booking.pk}/checkout/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['checkout_url'], 'https://checkout.stripe.com/deposit')
        # Full outstanding balance (500.00) charged in cents by default.
        kwargs = mock_create.call_args.kwargs
        self.assertEqual(kwargs['line_items'][0]['price_data']['unit_amount'], 50000)

    @patch('payments.views.stripe.checkout.Session.create')
    def test_owner_can_initiate_payment_for_any_booking(self, mock_create):
        mock_create.return_value = MagicMock(url='https://checkout.stripe.com/deposit')
        booking = make_booking(self.tenant, user=self.customer)
        self.client.force_authenticate(user=self.owner)
        resp = self.client.post(f'/api/payments/booking/{booking.pk}/checkout/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_other_customer_cannot_pay_someone_elses_booking(self):
        booking = make_booking(self.tenant, user=self.customer)
        self.client.force_authenticate(user=self.other_customer)
        resp = self.client.post(f'/api/payments/booking/{booking.pk}/checkout/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_amount_exceeding_outstanding_balance_rejected(self):
        booking = make_booking(self.tenant, user=self.customer, total_price='500.00', deposit_paid='0.00')
        self.client.force_authenticate(user=self.customer)
        resp = self.client.post(f'/api/payments/booking/{booking.pk}/checkout/', {'amount': '600.00'})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_fully_paid_booking_rejected(self):
        booking = make_booking(self.tenant, user=self.customer, total_price='500.00', deposit_paid='500.00')
        self.client.force_authenticate(user=self.customer)
        resp = self.client.post(f'/api/payments/booking/{booking.pk}/checkout/')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cancelled_booking_rejected(self):
        booking = make_booking(self.tenant, user=self.customer, status='cancelled')
        self.client.force_authenticate(user=self.customer)
        resp = self.client.post(f'/api/payments/booking/{booking.pk}/checkout/')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unauthenticated_cannot_pay(self):
        booking = make_booking(self.tenant, user=self.customer)
        resp = self.client.post(f'/api/payments/booking/{booking.pk}/checkout/')
        self.assertIn(resp.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])


# ── Booking deposit refund (admin-only) ──────────────────────────────────────

class BookingRefundTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('refundbiz')
        self.owner = make_user('owner@refundbiz.com', self.tenant)
        self.customer = make_user('cust@refundbiz.com', self.tenant, role='customer')
        self.client.defaults['HTTP_HOST'] = 'refundbiz.bizal.al'
        self.booking = make_booking(self.tenant, user=self.customer, total_price='500.00', deposit_paid='200.00')
        self.payment = Payment.objects.create(
            tenant=self.tenant, user=self.customer, booking=self.booking,
            amount=Decimal('200.00'), currency='ALL', payment_type='booking_deposit',
            status='completed', stripe_payment_intent='pi_test_123',
        )

    @patch('payments.views.stripe.Refund.create')
    def test_owner_can_refund_full_deposit(self, mock_refund):
        mock_refund.return_value = {'id': 're_test_1'}
        self.client.force_authenticate(user=self.owner)
        resp = self.client.post(f'/api/payments/booking/{self.booking.pk}/refund/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        mock_refund.assert_called_once_with(payment_intent='pi_test_123', amount=20000)
        self.payment.refresh_from_db()
        self.booking.refresh_from_db()
        self.assertEqual(self.payment.status, 'refunded')
        self.assertEqual(self.booking.deposit_paid, Decimal('0.00'))

    @patch('payments.views.stripe.Refund.create')
    def test_owner_can_partial_refund(self, mock_refund):
        mock_refund.return_value = {'id': 're_test_2'}
        self.client.force_authenticate(user=self.owner)
        resp = self.client.post(f'/api/payments/booking/{self.booking.pk}/refund/', {'amount': '50.00'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.payment.refresh_from_db()
        self.booking.refresh_from_db()
        # Partial refund: Payment stays 'completed', not 'refunded'.
        self.assertEqual(self.payment.status, 'completed')
        self.assertEqual(self.booking.deposit_paid, Decimal('150.00'))

    def test_customer_cannot_refund(self):
        self.client.force_authenticate(user=self.customer)
        resp = self.client.post(f'/api/payments/booking/{self.booking.pk}/refund/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_refund_with_no_payment_rejected(self):
        booking = make_booking(self.tenant, user=self.customer, total_price='500.00', deposit_paid='0.00')
        self.client.force_authenticate(user=self.owner)
        resp = self.client.post(f'/api/payments/booking/{booking.pk}/refund/')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_refund_amount_exceeding_payment_rejected(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.post(f'/api/payments/booking/{self.booking.pk}/refund/', {'amount': '9999.00'})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    @patch('payments.views.stripe.Refund.create')
    def test_two_partial_refunds_accumulate_to_full_status(self, mock_refund):
        # Regression test: previously every refund call validated/derived
        # is_full_refund against the ORIGINAL payment.amount instead of what
        # was actually still outstanding, so two partials that summed to the
        # full amount left payment.status stuck on 'completed' forever, and
        # 'refunded_amount' in metadata was overwritten (not accumulated) to
        # just the second call's amount.
        mock_refund.side_effect = [{'id': 're_a'}, {'id': 're_b'}]
        self.client.force_authenticate(user=self.owner)

        resp1 = self.client.post(f'/api/payments/booking/{self.booking.pk}/refund/', {'amount': '120.00'})
        self.assertEqual(resp1.status_code, status.HTTP_200_OK)
        self.payment.refresh_from_db()
        self.booking.refresh_from_db()
        self.assertEqual(self.payment.status, 'completed')  # partial, not yet full
        self.assertEqual(self.booking.deposit_paid, Decimal('80.00'))
        self.assertEqual(self.payment.metadata['refunded_amount'], '120.00')

        resp2 = self.client.post(f'/api/payments/booking/{self.booking.pk}/refund/', {'amount': '80.00'})
        self.assertEqual(resp2.status_code, status.HTTP_200_OK)
        self.payment.refresh_from_db()
        self.booking.refresh_from_db()
        self.assertEqual(self.payment.status, 'refunded')  # now cumulatively full
        self.assertEqual(self.booking.deposit_paid, Decimal('0.00'))
        # Cumulative total, not just the second call's 80.00.
        self.assertEqual(self.payment.metadata['refunded_amount'], '200.00')
        self.assertEqual(len(self.payment.metadata['refunds']), 2)
        self.assertEqual(mock_refund.call_count, 2)

    @patch('payments.views.stripe.Refund.create')
    def test_second_refund_validated_against_remaining_not_original(self, mock_refund):
        # A second refund request for more than what's actually left
        # (payment.amount - already_refunded) must be rejected locally with
        # a clean 400, not merely rely on Stripe rejecting it.
        mock_refund.return_value = {'id': 're_a'}
        self.client.force_authenticate(user=self.owner)

        resp1 = self.client.post(f'/api/payments/booking/{self.booking.pk}/refund/', {'amount': '150.00'})
        self.assertEqual(resp1.status_code, status.HTTP_200_OK)

        # Only 50.00 remains refundable; requesting 100.00 (which would have
        # passed the old "<= original payment.amount" check) must be rejected.
        resp2 = self.client.post(f'/api/payments/booking/{self.booking.pk}/refund/', {'amount': '100.00'})
        self.assertEqual(resp2.status_code, status.HTTP_400_BAD_REQUEST)
        mock_refund.assert_called_once()  # second call never reached Stripe

    @patch('payments.views.stripe.Refund.create')
    def test_refund_after_full_refund_rejected(self, mock_refund):
        mock_refund.return_value = {'id': 're_full'}
        self.client.force_authenticate(user=self.owner)
        resp1 = self.client.post(f'/api/payments/booking/{self.booking.pk}/refund/')
        self.assertEqual(resp1.status_code, status.HTTP_200_OK)

        resp2 = self.client.post(f'/api/payments/booking/{self.booking.pk}/refund/', {'amount': '1.00'})
        self.assertEqual(resp2.status_code, status.HTTP_400_BAD_REQUEST)
        mock_refund.assert_called_once()


# ── Webhook: booking-deposit checkout.session.completed ─────────────────────

class StripeWebhookBookingPaymentTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('webhookdeposit')
        self.customer = make_user('cust@webhookdeposit.com', self.tenant, role='customer')
        self.booking = make_booking(self.tenant, user=self.customer, total_price='500.00', deposit_paid='0.00')
        self.client.defaults['HTTP_HOST'] = 'webhookdeposit.bizal.al'

    @patch('payments.views.stripe.Webhook.construct_event')
    def test_booking_checkout_completed_records_payment_and_deposit(self, mock_event):
        mock_event.return_value = {
            'id': 'evt_booking_001',
            'type': 'checkout.session.completed',
            'data': {
                'object': {
                    'id': 'cs_test_booking',
                    'metadata': {'tenant_slug': 'webhookdeposit', 'booking_id': str(self.booking.pk)},
                    'amount_total': 20000,  # 200.00 in cents
                    'currency': 'all',
                    'payment_intent': 'pi_booking_test',
                }
            },
        }
        resp = self.client.post(
            '/api/payments/webhook/', data=json.dumps({}),
            content_type='application/json', HTTP_STRIPE_SIGNATURE='sig',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.deposit_paid, Decimal('200.00'))
        payment = Payment.objects.get(booking=self.booking)
        self.assertEqual(payment.status, 'completed')
        self.assertEqual(payment.payment_type, 'booking_deposit')
        self.assertEqual(payment.amount, Decimal('200.00'))

    @patch('payments.views.stripe.Webhook.construct_event')
    def test_booking_checkout_completed_redelivery_does_not_double_count_deposit(self, mock_event):
        """
        Regression: booking.deposit_paid was being incremented unconditionally
        every time the checkout.session.completed handler ran. The Payment
        row is correctly idempotent on stripe_session_id, but deposit_paid
        is not — the Redis idempotency cache (stripe_event:{id}, 24h TTL) is
        the only thing normally preventing a redelivered/duplicate webhook
        from re-entering this branch. If that cache key is ever lost (Redis
        eviction, flush, deploy) before Stripe's retry window closes, the
        handler runs again for the same event, and deposit_paid must still
        only be credited once.
        """
        from django.core.cache import cache

        mock_event.return_value = {
            'id': 'evt_booking_redelivery',
            'type': 'checkout.session.completed',
            'data': {
                'object': {
                    'id': 'cs_test_redelivery',
                    'metadata': {'tenant_slug': 'webhookdeposit', 'booking_id': str(self.booking.pk)},
                    'amount_total': 20000,  # 200.00 in cents
                    'currency': 'all',
                    'payment_intent': 'pi_booking_redelivery',
                }
            },
        }
        resp1 = self.client.post(
            '/api/payments/webhook/', data=json.dumps({}),
            content_type='application/json', HTTP_STRIPE_SIGNATURE='sig',
        )
        self.assertEqual(resp1.status_code, status.HTTP_200_OK)

        # Simulate the idempotency cache key being lost (eviction/flush)
        # before Stripe's retry window closes, so the redelivered webhook
        # reaches _handle_event() a second time.
        cache.delete('stripe_event:evt_booking_redelivery')

        resp2 = self.client.post(
            '/api/payments/webhook/', data=json.dumps({}),
            content_type='application/json', HTTP_STRIPE_SIGNATURE='sig',
        )
        self.assertEqual(resp2.status_code, status.HTTP_200_OK)

        self.booking.refresh_from_db()
        self.assertEqual(self.booking.deposit_paid, Decimal('200.00'))
        self.assertEqual(
            Payment.objects.filter(booking=self.booking, payment_type='booking_deposit').count(), 1,
        )

    @patch('payments.views.stripe.Webhook.construct_event')
    def test_booking_checkout_completed_unknown_booking_does_not_crash(self, mock_event):
        mock_event.return_value = {
            'id': 'evt_booking_002',
            'type': 'checkout.session.completed',
            'data': {
                'object': {
                    'id': 'cs_test_missing',
                    'metadata': {'tenant_slug': 'webhookdeposit', 'booking_id': '00000000-0000-0000-0000-000000000000'},
                    'amount_total': 10000,
                    'currency': 'all',
                }
            },
        }
        resp = self.client.post(
            '/api/payments/webhook/', data=json.dumps({}),
            content_type='application/json', HTTP_STRIPE_SIGNATURE='sig',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(Payment.objects.filter(payment_type='booking_deposit').exists())


# ── Online-payments opt-in gate ──────────────────────────────────────────────

class BookingCheckoutOptInGateTest(TestCase):
    """
    accepts_online_payments defaults to False. Cash-only tenants (the
    common case for small businesses wanting to avoid Stripe's per-
    transaction fee) must never have the checkout endpoint usable until
    they explicitly opt in via tenant settings.
    """
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('cashonlybiz', accepts_online_payments=False)
        self.customer = make_user('cust@cashonlybiz.com', self.tenant, role='customer')
        self.client.defaults['HTTP_HOST'] = 'cashonlybiz.bizal.al'
        self.booking = make_booking(self.tenant, user=self.customer)
        self.client.force_authenticate(user=self.customer)

    def test_checkout_blocked_when_opted_out(self):
        resp = self.client.post(f'/api/payments/booking/{self.booking.pk}/checkout/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    @patch('payments.views.stripe.checkout.Session.create')
    def test_checkout_allowed_once_opted_in(self, mock_create):
        mock_create.return_value = MagicMock(url='https://checkout.stripe.com/deposit')
        self.tenant.accepts_online_payments = True
        self.tenant.save()
        resp = self.client.post(f'/api/payments/booking/{self.booking.pk}/checkout/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_defaults_to_false_on_new_tenant(self):
        t = Tenant.objects.create(name='Fresh Biz', slug='freshbiz', plan='pro', is_active=True, business_type='restaurant')
        self.assertFalse(t.accepts_online_payments)


# ── Booking deposit checkout — customer-chosen pay_currency ─────────────────

class BookingCheckoutPayCurrencyTest(TestCase):
    """
    create_booking_checkout: the ledger amount is always ALL (see the
    comment on Tenant.currency in tenants/models.py), but the customer may
    choose to have Stripe charge them in EUR or USD instead — converted at
    checkout time via tenants/fx.py, using whatever live rate
    refresh_fx_rates has most recently cached. There is no hardcoded
    fallback: the test cache backend (DummyCache) never has a rate cached
    unless a test explicitly patches tenants.fx.cache with a real backend
    and calls set_rate() first — tests that don't do so exercise the
    "currency temporarily unavailable" (503) path instead.
    """
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('fxdepositbiz')
        self.customer = make_user('cust@fxdepositbiz.com', self.tenant, role='customer')
        self.client.defaults['HTTP_HOST'] = 'fxdepositbiz.bizal.al'
        self.client.force_authenticate(user=self.customer)

    def _use_real_cache_with_rates(self, **rates):
        from django.core.cache.backends.locmem import LocMemCache
        from tenants.fx import set_rate
        real_cache = LocMemCache('fx-checkout-test', {})
        real_cache.clear()
        patcher = patch('tenants.fx.cache', real_cache)
        patcher.start()
        self.addCleanup(patcher.stop)
        for currency, rate in rates.items():
            set_rate(currency, rate)
        return real_cache

    @patch('payments.views.stripe.checkout.Session.create')
    def test_default_pay_currency_is_all(self, mock_create):
        # ALL needs no rate/conversion, so this must work even with no live
        # rate cached anywhere.
        mock_create.return_value = MagicMock(url='https://checkout.stripe.com/deposit')
        booking = make_booking(self.tenant, user=self.customer)
        resp = self.client.post(f'/api/payments/booking/{booking.pk}/checkout/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        kwargs = mock_create.call_args.kwargs
        self.assertEqual(kwargs['line_items'][0]['price_data']['currency'], 'all')
        self.assertEqual(kwargs['line_items'][0]['price_data']['unit_amount'], 50000)
        self.assertEqual(kwargs['metadata']['pay_currency'], 'ALL')
        self.assertEqual(kwargs['metadata']['amount_all'], '500.00')

    @patch('payments.views.stripe.checkout.Session.create')
    def test_customer_can_choose_eur_when_rate_is_live(self, mock_create):
        eur_rate = Decimal('105.00')
        self._use_real_cache_with_rates(EUR=eur_rate)
        mock_create.return_value = MagicMock(url='https://checkout.stripe.com/deposit')
        booking = make_booking(self.tenant, user=self.customer, total_price='10500.00', deposit_paid='0.00')
        resp = self.client.post(
            f'/api/payments/booking/{booking.pk}/checkout/', {'pay_currency': 'eur'},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        kwargs = mock_create.call_args.kwargs
        self.assertEqual(kwargs['line_items'][0]['price_data']['currency'], 'eur')
        expected_eur = (Decimal('10500.00') / eur_rate).quantize(Decimal('0.01'))
        self.assertEqual(
            kwargs['line_items'][0]['price_data']['unit_amount'],
            int((expected_eur * 100).to_integral_value()),
        )
        self.assertEqual(kwargs['metadata']['amount_all'], '10500.00')

    @patch('payments.views.stripe.checkout.Session.create')
    def test_customer_can_choose_usd_when_rate_is_live(self, mock_create):
        self._use_real_cache_with_rates(USD=Decimal('97.00'))
        mock_create.return_value = MagicMock(url='https://checkout.stripe.com/deposit')
        booking = make_booking(self.tenant, user=self.customer)
        resp = self.client.post(
            f'/api/payments/booking/{booking.pk}/checkout/', {'pay_currency': 'usd'},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        kwargs = mock_create.call_args.kwargs
        self.assertEqual(kwargs['line_items'][0]['price_data']['currency'], 'usd')

    def test_unsupported_pay_currency_rejected(self):
        booking = make_booking(self.tenant, user=self.customer)
        resp = self.client.post(
            f'/api/payments/booking/{booking.pk}/checkout/', {'pay_currency': 'gbp'},
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_eur_rejected_with_503_when_no_live_rate_cached(self):
        # Tracked currency, but nothing cached (test cache backend is
        # DummyCache and nothing patched it) — must reject rather than
        # silently charge at a fabricated rate.
        booking = make_booking(self.tenant, user=self.customer)
        resp = self.client.post(
            f'/api/payments/booking/{booking.pk}/checkout/', {'pay_currency': 'eur'},
        )
        self.assertEqual(resp.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)

    def test_available_pay_currencies_endpoint_reflects_cache(self):
        resp = self.client.get('/api/payments/available-currencies/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['available_pay_currencies'], ['ALL'])

        self._use_real_cache_with_rates(EUR=Decimal('105.00'))
        resp = self.client.get('/api/payments/available-currencies/')
        self.assertEqual(resp.data['available_pay_currencies'], ['ALL', 'EUR'])


# ── Webhook: booking-deposit checkout completed in a foreign pay_currency ───

class StripeWebhookBookingPaymentForeignCurrencyTest(TestCase):
    """
    checkout.session.completed for a booking paid in EUR/USD must still
    record the Payment and increment Booking.deposit_paid in ALL — using
    the amount_all figure threaded through session metadata by
    create_booking_checkout, not the charged amount/currency Stripe
    reports in the webhook payload itself.
    """
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('webhookfx')
        self.customer = make_user('cust@webhookfx.com', self.tenant, role='customer')
        self.booking = make_booking(self.tenant, user=self.customer, total_price='500.00', deposit_paid='0.00')
        self.client.defaults['HTTP_HOST'] = 'webhookfx.bizal.al'

    def _use_real_cache_with_rates(self, **rates):
        from django.core.cache.backends.locmem import LocMemCache
        from tenants.fx import set_rate
        real_cache = LocMemCache('fx-webhook-test', {})
        real_cache.clear()
        patcher = patch('tenants.fx.cache', real_cache)
        patcher.start()
        self.addCleanup(patcher.stop)
        for currency, rate in rates.items():
            set_rate(currency, rate)
        return real_cache

    @patch('payments.views.stripe.Webhook.construct_event')
    def test_eur_checkout_records_all_amount_on_ledger(self, mock_event):
        # amount_all is present in metadata, so the webhook uses it
        # directly and never calls convert_to_all — no live rate needs to
        # be cached for this test. eur_rate here is only used to construct
        # a plausible fake "amount Stripe charged" for the mock event.
        eur_rate = Decimal('105.00')
        charged_eur = (Decimal('500.00') / eur_rate).quantize(Decimal('0.01'))
        mock_event.return_value = {
            'id': 'evt_booking_fx_001',
            'type': 'checkout.session.completed',
            'data': {
                'object': {
                    'id': 'cs_test_booking_fx',
                    'metadata': {
                        'tenant_slug': 'webhookfx',
                        'booking_id': str(self.booking.pk),
                        'amount_all': '500.00',
                        'pay_currency': 'EUR',
                    },
                    'amount_total': int((charged_eur * 100).to_integral_value()),
                    'currency': 'eur',
                    'payment_intent': 'pi_booking_fx_test',
                }
            },
        }
        resp = self.client.post(
            '/api/payments/webhook/', data=json.dumps({}),
            content_type='application/json', HTTP_STRIPE_SIGNATURE='sig',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.booking.refresh_from_db()
        # Ledger stays ALL regardless of the EUR charge.
        self.assertEqual(self.booking.deposit_paid, Decimal('500.00'))
        payment = Payment.objects.get(booking=self.booking)
        self.assertEqual(payment.currency, 'ALL')
        self.assertEqual(payment.amount, Decimal('500.00'))
        self.assertEqual(payment.metadata['charged_currency'], 'EUR')
        self.assertEqual(payment.metadata['charged_amount'], str(charged_eur))

    @patch('payments.views.stripe.Webhook.construct_event')
    def test_missing_amount_all_metadata_falls_back_to_fx_conversion_when_rate_live(self, mock_event):
        # Simulates a checkout session created before pay-currency support
        # existed (no amount_all in metadata) — must not crash, and should
        # convert the charged USD amount back to ALL using whatever rate is
        # currently cached.
        usd_rate = Decimal('97.00')
        self._use_real_cache_with_rates(USD=usd_rate)
        mock_event.return_value = {
            'id': 'evt_booking_fx_002',
            'type': 'checkout.session.completed',
            'data': {
                'object': {
                    'id': 'cs_test_booking_legacy',
                    'metadata': {'tenant_slug': 'webhookfx', 'booking_id': str(self.booking.pk)},
                    'amount_total': 10000,  # 100.00 USD
                    'currency': 'usd',
                    'payment_intent': 'pi_booking_legacy',
                }
            },
        }
        resp = self.client.post(
            '/api/payments/webhook/', data=json.dumps({}),
            content_type='application/json', HTTP_STRIPE_SIGNATURE='sig',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        payment = Payment.objects.get(booking=self.booking)
        self.assertEqual(payment.currency, 'ALL')
        expected_all = (Decimal('100.00') * usd_rate).quantize(Decimal('0.01'))
        self.assertEqual(payment.amount, expected_all)

    @patch('payments.views.stripe.Webhook.construct_event')
    def test_missing_amount_all_metadata_and_no_live_rate_uses_last_resort(self, mock_event):
        # Same legacy-session scenario, but this time no live rate is
        # cached either (DummyCache, nothing patched). Stripe has already
        # charged the customer real money by the time this webhook fires,
        # so we must still record *something* rather than drop the
        # webhook — falling back to treating the charged figure as if it
        # were already ALL, best-effort.
        mock_event.return_value = {
            'id': 'evt_booking_fx_003',
            'type': 'checkout.session.completed',
            'data': {
                'object': {
                    'id': 'cs_test_booking_legacy_no_rate',
                    'metadata': {'tenant_slug': 'webhookfx', 'booking_id': str(self.booking.pk)},
                    'amount_total': 10000,  # 100.00 USD
                    'currency': 'usd',
                    'payment_intent': 'pi_booking_legacy_no_rate',
                }
            },
        }
        resp = self.client.post(
            '/api/payments/webhook/', data=json.dumps({}),
            content_type='application/json', HTTP_STRIPE_SIGNATURE='sig',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        payment = Payment.objects.get(booking=self.booking)
        self.assertEqual(payment.currency, 'ALL')
        self.assertEqual(payment.amount, Decimal('100.00'))  # last-resort: charged amount treated as ALL


# ── Refund: converts back into the currency actually charged ────────────────

class BookingRefundForeignCurrencyTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('refundfxbiz')
        self.owner = make_user('owner@refundfxbiz.com', self.tenant)
        self.client.defaults['HTTP_HOST'] = 'refundfxbiz.bizal.al'
        self.booking = make_booking(self.tenant, total_price='500.00', deposit_paid='200.00')
        # Payment.amount is ALL (200.00); the customer actually paid in EUR
        # at checkout, recorded in metadata as charged_amount/charged_currency.
        self.payment = Payment.objects.create(
            tenant=self.tenant, booking=self.booking,
            amount=Decimal('200.00'), currency='ALL', payment_type='booking_deposit',
            status='completed', stripe_payment_intent='pi_fx_test_1',
            metadata={'charged_amount': '2.00', 'charged_currency': 'EUR'},
        )

    @patch('payments.views.stripe.Refund.create')
    def test_full_refund_uses_charged_currency_amount(self, mock_refund):
        mock_refund.return_value = {'id': 're_fx_test_1'}
        self.client.force_authenticate(user=self.owner)
        resp = self.client.post(f'/api/payments/booking/{self.booking.pk}/refund/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        # Refund is issued in the originally-charged currency/amount (2.00
        # EUR = 200 cents), not the ALL ledger amount (200.00 ALL).
        mock_refund.assert_called_once_with(payment_intent='pi_fx_test_1', amount=200)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.deposit_paid, Decimal('0.00'))

    @patch('payments.views.stripe.Refund.create')
    def test_partial_refund_scales_charged_currency_amount_proportionally(self, mock_refund):
        mock_refund.return_value = {'id': 're_fx_test_2'}
        self.client.force_authenticate(user=self.owner)
        resp = self.client.post(f'/api/payments/booking/{self.booking.pk}/refund/', {'amount': '100.00'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        # Half of the ALL amount refunded (100/200) => half of the charged
        # EUR amount (1.00 EUR = 100 cents).
        mock_refund.assert_called_once_with(payment_intent='pi_fx_test_1', amount=100)
