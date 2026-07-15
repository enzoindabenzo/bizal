"""
BizAL — django-admin dashboard callback.

Wired up via UNFOLD['DASHBOARD_CALLBACK'] in settings/base.py; Unfold calls
dashboard_callback(request, context) when rendering /django-admin/'s index
page and passes the returned context to frontend/templates/admin/index.html.

Builds two things:
  1. bizal_kpis / bizal_recent_* — the KPI cards + "recent items" panels.
  2. bizal_analytics — chart-ready JSON series (tenant signups over the
     last 30 days, plan distribution, platform activity volume over the
     last 14 days) rendered client-side with Chart.js in admin/index.html.

Deliberately reads the same tables each app's admin.py registrations
already use (Tenant, WebhookEvent, ActivityLog, CustomerSubscription)
rather than introducing a new API surface — one source of truth, viewable
natively in django-admin.

No revenue/MRR figures are computed here: there is no EUR-per-plan constant
anywhere in the codebase (pricing lives in Stripe), so a computed MRR number
would just be a guess dressed up as data. If real revenue reporting is
wanted here later, it should pull from Stripe (or from actual invoice
amounts) rather than inferring price from `Tenant.plan`.
"""
import json
from datetime import timedelta

from django.db.models import Count
from django.db.models.functions import TruncDate
from django.utils import timezone

from tenants.models import Tenant, PLAN_TRIAL

# Fixed hex order for the plan-distribution chart so colours stay stable
# across renders regardless of dict/queryset ordering (JS reads this list
# in lockstep with PLAN_CHART_COLORS by index).
PLAN_CHART_COLORS = ['#f59e0b', '#78716c', '#0ea5e9', '#22c55e', '#a855f7', '#ef4444']


def _daily_counts(queryset, date_field, days):
    """
    Daily row counts for the last `days` days (oldest → newest), zero-filled
    so gaps show as 0 rather than skipping the date entirely — a chart with
    missing x-axis points is misleading, it looks like time compressed
    rather than like nothing happened that day.

    Generic over any queryset + date/datetime field, so it's reused for
    both the tenant-signups series and the activity-volume series instead
    of duplicating the bucketing logic per metric.
    """
    now = timezone.now()
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)

    counts_by_day = {
        row['day']: row['n']
        for row in (
            queryset.filter(**{f'{date_field}__gte': start})
            .annotate(day=TruncDate(date_field))
            .values('day')
            .annotate(n=Count('id'))
        )
    }

    labels, values = [], []
    for i in range(days):
        day = (start + timedelta(days=i)).date()
        labels.append(day.strftime('%d %b'))
        values.append(counts_by_day.get(day, 0))
    return labels, values


def dashboard_callback(request, context):
    now = timezone.now()
    week_ago = now - timedelta(days=7)

    tenants = Tenant.objects.all()

    plan_field_choices = Tenant._meta.get_field('plan').choices
    plan_counts = {
        choice_value: tenants.filter(plan=choice_value).count()
        for choice_value, _label in plan_field_choices
    }

    trial_tenants = tenants.filter(plan=PLAN_TRIAL)
    trials_expiring_soon = [
        t for t in trial_tenants
        if t.trial_ends_at and 0 <= (t.trial_ends_at - now).days <= 3
    ]

    context.update({
        'bizal_kpis': {
            'total_tenants': tenants.count(),
            'active_tenants': tenants.filter(is_active=True).count(),
            'inactive_tenants': tenants.filter(is_active=False).count(),
            'new_this_week': tenants.filter(created_at__gte=week_ago).count(),
            'plan_counts': plan_counts,
            'trial_count': trial_tenants.count(),
            'trials_expiring_soon': len(trials_expiring_soon),
        },
        'bizal_recent_tenants': tenants.order_by('-created_at')[:6],
        'bizal_expiring_trials': sorted(
            trials_expiring_soon, key=lambda t: t.trial_ends_at
        )[:6],
    })

    # ── Analytics: signups trend (last 30 days) + plan distribution ─────
    # No revenue/MRR here for the same reason noted in the module
    # docstring — everything charted is a real, directly-queried count.
    signup_labels, signup_values = _daily_counts(tenants, 'created_at', days=30)
    context['bizal_analytics'] = {
        'signups_labels': json.dumps(signup_labels),
        'signups_values': json.dumps(signup_values),
        'signups_total_30d': sum(signup_values),
        'plan_labels': json.dumps([str(label) for _v, label in plan_field_choices]),
        'plan_values': json.dumps([plan_counts.get(v, 0) for v, _l in plan_field_choices]),
        'plan_colors': json.dumps(PLAN_CHART_COLORS[:len(plan_field_choices)]),
        'activity_labels': json.dumps([]),
        'activity_values': json.dumps([]),
    }

    try:
        from payments.models import WebhookEvent
        context['bizal_recent_webhook_failures'] = list(
            WebhookEvent.objects.filter(status='failed').order_by('-created_at')[:5]
        )
    except Exception:
        context['bizal_recent_webhook_failures'] = []

    try:
        from activity.models import ActivityLog
        context['bizal_recent_activity'] = list(
            ActivityLog.objects.select_related('tenant').order_by('-created_at')[:8]
        )
        # ── Analytics: platform activity volume (last 14 days) ──────────
        activity_labels, activity_values = _daily_counts(
            ActivityLog.objects.all(), 'created_at', days=14
        )
        context['bizal_analytics']['activity_labels'] = json.dumps(activity_labels)
        context['bizal_analytics']['activity_values'] = json.dumps(activity_values)
    except Exception:
        context['bizal_recent_activity'] = []

    return context
