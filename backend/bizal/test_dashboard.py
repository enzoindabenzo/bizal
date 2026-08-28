"""
Coverage for bizal/dashboard.py::dashboard_callback and its private
_daily_counts helper. Pure-function callback (no view/URL involved), so
it's tested by calling it directly with a dummy request and an empty
context dict, the same way Unfold invokes it.
"""
import json
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from activity.models import ActivityLog
from payments.models import WebhookEvent
from tenants.models import Tenant

from bizal.dashboard import dashboard_callback, _daily_counts


class DailyCountsHelperTests(TestCase):
    def test_zero_fills_days_with_no_new_rows(self):
        baseline = Tenant.objects.all().count()
        labels, values = _daily_counts(Tenant.objects.all(), 'created_at', days=5)
        self.assertEqual(len(labels), 5)
        self.assertEqual(len(values), 5)
        self.assertEqual(sum(values), baseline)

    def test_counts_rows_on_correct_day(self):
        baseline = Tenant.objects.all().count()
        Tenant.objects.create(name='A', slug='a-daily', business_type='restaurant')
        Tenant.objects.create(name='B', slug='b-daily', business_type='restaurant')
        labels, values = _daily_counts(Tenant.objects.all(), 'created_at', days=3)
        self.assertEqual(values[-1], baseline + 2)  # today's bucket


class DashboardCallbackTests(TestCase):
    def setUp(self):
        self.request = None  # dashboard_callback doesn't touch request

    def test_empty_state_kpis(self):
        context = dashboard_callback(self.request, {})
        kpis = context['bizal_kpis']
        # A sentinel "main" tenant (plan=enterprise, is_active=True) is
        # created by a data migration, so "empty" means "just that one".
        self.assertEqual(kpis['total_tenants'], 1)
        self.assertEqual(kpis['active_tenants'], 1)
        self.assertEqual(kpis['inactive_tenants'], 0)
        self.assertEqual(kpis['trial_count'], 0)
        self.assertEqual(kpis['trials_expiring_soon'], 0)
        self.assertEqual(context['bizal_expiring_trials'], [])

    def test_kpis_with_mixed_tenants(self):
        now = timezone.now()
        Tenant.objects.create(
            name='Active Pro', slug='active-pro', business_type='restaurant',
            plan='pro', is_active=True,
        )
        Tenant.objects.create(
            name='Inactive Starter', slug='inactive-starter', business_type='restaurant',
            plan='starter', is_active=False,
        )
        # A trial expiring in 2 days (within the 0-3 day "expiring soon" window)
        expiring_trial = Tenant.objects.create(
            name='Soon Expiring', slug='soon-expiring', business_type='restaurant',
            plan='trial', is_active=True, trial_ends_at=now + timedelta(days=2),
        )
        # A trial expiring far in the future — should NOT count as "soon"
        Tenant.objects.create(
            name='Far Trial', slug='far-trial', business_type='restaurant',
            plan='trial', is_active=True, trial_ends_at=now + timedelta(days=10),
        )
        # A trial with no trial_ends_at set yet — must not blow up the comprehension
        Tenant.objects.create(
            name='No Clock Trial', slug='no-clock-trial', business_type='restaurant',
            plan='trial', is_active=False, trial_ends_at=None,
        )
        # An already-expired trial — outside the 0-3 day window (negative days)
        Tenant.objects.create(
            name='Expired Trial', slug='expired-trial-dash', business_type='restaurant',
            plan='trial', is_active=True, trial_ends_at=now - timedelta(days=1),
        )

        context = dashboard_callback(self.request, {})
        kpis = context['bizal_kpis']
        # +1 for the sentinel "main" tenant created by data migration 0019.
        self.assertEqual(kpis['total_tenants'], 7)
        self.assertEqual(kpis['active_tenants'], 5)
        self.assertEqual(kpis['inactive_tenants'], 2)
        self.assertEqual(kpis['trial_count'], 4)
        self.assertEqual(kpis['trials_expiring_soon'], 1)
        self.assertIn('pro', kpis['plan_counts'])

        expiring = context['bizal_expiring_trials']
        self.assertEqual(len(expiring), 1)
        self.assertEqual(expiring[0].slug, expiring_trial.slug)

        recent = list(context['bizal_recent_tenants'])
        self.assertEqual(len(recent), 6)

    def test_analytics_series_are_valid_json(self):
        Tenant.objects.create(name='X', slug='x-analytics', business_type='restaurant', plan='pro')
        context = dashboard_callback(self.request, {})
        analytics = context['bizal_analytics']

        signup_labels = json.loads(analytics['signups_labels'])
        signup_values = json.loads(analytics['signups_values'])
        self.assertEqual(len(signup_labels), 30)
        self.assertEqual(len(signup_values), 30)
        self.assertEqual(analytics['signups_total_30d'], sum(signup_values))

        plan_labels = json.loads(analytics['plan_labels'])
        plan_values = json.loads(analytics['plan_values'])
        plan_colors = json.loads(analytics['plan_colors'])
        self.assertEqual(len(plan_labels), len(plan_values))
        self.assertEqual(len(plan_colors), len(plan_labels))

    def test_webhook_failures_included_when_present(self):
        WebhookEvent.objects.create(
            stripe_event_id='evt_1', event_type='invoice.payment_failed',
            status='failed', error_message='card declined',
        )
        WebhookEvent.objects.create(
            stripe_event_id='evt_2', event_type='invoice.paid',
            status='processed',
        )
        context = dashboard_callback(self.request, {})
        failures = context['bizal_recent_webhook_failures']
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].stripe_event_id, 'evt_1')

    def test_webhook_import_failure_falls_back_to_empty_list(self):
        with patch('payments.models.WebhookEvent.objects.filter', side_effect=Exception('db down')):
            context = dashboard_callback(self.request, {})
        self.assertEqual(context['bizal_recent_webhook_failures'], [])

    def test_activity_feed_and_volume_series_included_when_present(self):
        tenant = Tenant.objects.create(
            name='Activity Co', slug='activity-co', business_type='restaurant',
        )
        ActivityLog.objects.create(
            tenant=tenant, verb='tenant.activated',
            description='Activated by superadmin',
        )
        context = dashboard_callback(self.request, {})
        recent_activity = context['bizal_recent_activity']
        self.assertEqual(len(recent_activity), 1)

        activity_labels = json.loads(context['bizal_analytics']['activity_labels'])
        activity_values = json.loads(context['bizal_analytics']['activity_values'])
        self.assertEqual(len(activity_labels), 14)
        self.assertEqual(sum(activity_values), 1)

    def test_activity_import_failure_falls_back_to_empty_list_and_series(self):
        with patch(
            'activity.models.ActivityLog.objects.select_related',
            side_effect=Exception('db down'),
        ):
            context = dashboard_callback(self.request, {})
        self.assertEqual(context['bizal_recent_activity'], [])
        # activity_labels/values stay at their pre-set empty-list defaults
        self.assertEqual(json.loads(context['bizal_analytics']['activity_labels']), [])
        self.assertEqual(json.loads(context['bizal_analytics']['activity_values']), [])
