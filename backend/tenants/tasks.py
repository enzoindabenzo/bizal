"""
Celery tasks for tenant lifecycle management.
"""
import math
import datetime
from decimal import Decimal

import requests
from celery import shared_task
from django.db.utils import OperationalError
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings


@shared_task
def expire_trials():
    """
    Runs daily. Deactivates expired trial tenants (is_active=False).
    Sends an email nudge to the owner.

    IMPORTANT: This task deliberately does NOT change `plan` away from
    PLAN_TRIAL. `tenants/middleware.py::_enforce_trial` follows the same
    contract for the same reason: `Tenant.trial_expired` only reports True
    while `plan == PLAN_TRIAL` (see `tenants/models.py`). If this task
    downgraded `plan` to PLAN_STARTER, `trial_expired` would silently flip
    back to False the moment this task ran, even though the tenant is
    deactivated — the frontend would lose the signal it uses to show the
    "upgrade to continue" screen and would show a generic inactive error
    instead. Keep `plan` untouched here; only `is_active` changes.
    """
    from .models import Tenant, PLAN_TRIAL
    from django.db.models import Prefetch
    from accounts.models import User

    now = timezone.now()
    # MED-1 / LOW-2 FIX: prefetch each tenant's owner in the same round trip
    # instead of issuing one `tenant.users.filter(role='owner').first()` query
    # per expired tenant inside the loop. With N tenants expiring on the same
    # day this previously produced N+1 queries per run.
    expired = Tenant.objects.filter(
        plan=PLAN_TRIAL,
        trial_ends_at__lt=now,
        is_active=True,
    ).prefetch_related(
        Prefetch('users', queryset=User.objects.filter(role='owner'), to_attr='_prefetched_owners')
    )

    count = 0
    for tenant in expired:
        Tenant.objects.filter(pk=tenant.pk).update(is_active=False, trial_warning_sent_at=None)  # LOW-1 FIX: clear warning flag so re-activated tenants receive new trial warning
        from django.core.cache import cache
        cache.delete(f'tenant:{tenant.slug}')
        cache.delete(f'trial_expired:{tenant.slug}')
        owner = tenant._prefetched_owners[0] if tenant._prefetched_owners else None
        _send_trial_expired_email(tenant, owner=owner)
        count += 1

    return f"Expired and deactivated {count} trial tenant(s)."


@shared_task
def send_trial_warning_emails():
    """
    Runs daily. Sends a 3-day warning email to tenants whose trial expires soon.
    """
    from .models import Tenant, PLAN_TRIAL
    from django.db.models import Prefetch
    from accounts.models import User

    now = timezone.now()
    warning_window_end = now + datetime.timedelta(days=3)

    tenants = Tenant.objects.filter(
        plan=PLAN_TRIAL,
        is_active=True,
        trial_ends_at__range=(now, warning_window_end),
        # Guard: only send once. Without this, the daily task re-matches the same
        # tenant for up to 3 consecutive days (once per day while trial_ends_at
        # remains within the 3-day window), sending 3 emails instead of one.
        trial_warning_sent_at__isnull=True,
    ).prefetch_related(
        # MED-1 / LOW-2 FIX: avoid N+1 owner lookups in the loop below.
        Prefetch('users', queryset=User.objects.filter(role='owner'), to_attr='_prefetched_owners')
    )

    count = 0
    for tenant in tenants:
        days_left = max(0, math.ceil((tenant.trial_ends_at - now).total_seconds() / 86400))  # MED-7 FIX: use math.ceil instead of double-negation trick; avoids float boundary off-by-one
        owner = tenant._prefetched_owners[0] if tenant._prefetched_owners else None
        _send_trial_warning_email(tenant, days_left, owner=owner)
        # LOW-2 FIX (v53): Conditional update guards against concurrent Celery
        # workers both reading the same isnull=True result set and sending
        # duplicate warning emails. If another worker already set
        # trial_warning_sent_at, updated == 0 and we skip the counter increment.
        # The first duplicate send (pre-commit race) is unavoidable but subsequent
        # daily runs are idempotent, matching the pattern in send_appointment_reminders.
        updated = Tenant.objects.filter(
            pk=tenant.pk, trial_warning_sent_at__isnull=True
        ).update(trial_warning_sent_at=now)
        if updated:
            count += 1

    return f"Sent trial warning to {count} tenant(s)."


import logging as _logging
_tasks_logger = _logging.getLogger(__name__)


def _send_trial_expired_email(tenant, owner=None):
    if owner is None:
        owner = tenant.users.filter(role='owner').first()
    if not owner:
        return
    # MEDIUM-2 / LOW-3 FIX: Skip anonymised owner accounts. MeDeleteView sets
    # email='deleted_<uuid>@deleted.bizal.al' and is_active=False. The Prefetch
    # in expire_trials() filters by role='owner' but not by is_active, so an
    # anonymised owner can still be returned here. Sending to a deleted address
    # produces a broken salutation ('Pershendetje deleted_<uuid>') and a
    # bounced email. Former owners should receive no further platform mail.
    if not owner.is_active or not owner.email or 'deleted.bizal.al' in owner.email:
        return
    try:
        send_mail(
            subject='Periudha juaj e provës BizAL ka përfunduar',
            message=(
                f'Pershendetje {owner.display_name},\n\n'
                f'Periudha 14-ditore e provës për "{tenant.name}" ka përfunduar.\n\n'
                f'Për të vazhduar të përdorni platformën, zgjidhni një plan:\n'
                f'{settings.FRONTEND_BASE_URL}/onboarding/?step=plan\n\n'
                f'Nëse keni pyetje, shkruani te support@bizal.al\n\n'
                f'BizAL Team'
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[owner.email],
            # M-2 FIX: fail_silently=False so SMTP errors raise into the except
            # block and are logged. Previously fail_silently=True swallowed all
            # SMTP failures silently — trial-expiry emails could stop delivering
            # entirely with no log entry, no retry, and no alerting.
            fail_silently=False,
        )
    except Exception as exc:
        _tasks_logger.error(
            "tenants: failed to send trial-expired email to tenant %s (owner %s): %s",
            tenant.slug, owner.email, exc,
        )


def _send_trial_warning_email(tenant, days_left, owner=None):
    if owner is None:
        owner = tenant.users.filter(role='owner').first()
    if not owner:
        return
    # MEDIUM-2 / LOW-3 FIX: same anonymised-owner guard as _send_trial_expired_email.
    if not owner.is_active or not owner.email or 'deleted.bizal.al' in owner.email:
        return
    try:
        send_mail(
            subject=f'Trialu juaj BizAL skadon në {days_left} ditë',
            message=(
                f'Pershendetje {owner.display_name},\n\n'
                f'Periudha e provës për "{tenant.name}" mbaron pas {days_left} ditësh.\n\n'
                f'Zgjidhni planin tuaj tani dhe ruani aksesin:\n'
                f'{settings.FRONTEND_BASE_URL}/onboarding/?step=plan\n\n'
                f'BizAL Team'
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[owner.email],
            # M-2 FIX: fail_silently=False — same rationale as _send_trial_expired_email.
            fail_silently=False,
        )
    except Exception as exc:
        _tasks_logger.error(
            "tenants: failed to send trial-warning email to tenant %s (owner %s): %s",
            tenant.slug, owner.email, exc,
        )


@shared_task(bind=True, max_retries=3, autoretry_for=(OperationalError,), retry_backoff=True)
def apply_referral_credits_for_active_tenants(self):
    """
    Applies referral credits for any referrals where the referred tenant
    just became active (e.g. upgraded to a paid plan). Runs daily.
    """
    from .models import TenantReferral

    pending = TenantReferral.objects.filter(
        applied=False,
        referred__is_active=True,
        # Deliberately excludes 'starter': referral credit only applies when
        # the referred tenant converts to a paid Pro or Enterprise
        # subscription, not a free/entry-level Starter plan. This is a
        # product policy decision (reward paying upgrades only) — update
        # this list if that business rule changes.
        referred__plan__in=['pro', 'enterprise'],
    ).select_related('referrer', 'referred')

    errors = 0
    count = 0
    for ref in pending:
        # MED-2 FIX: The outer transaction.atomic() + select_for_update() that
        # previously lived here was the original concurrency guard. It became
        # redundant when apply_credit() was made self-locking (prev-audit MED-4
        # fix): apply_credit() now acquires its own transaction.atomic() +
        # select_for_update() + applied=False re-check internally, making it
        # fully idempotent and concurrency-safe on its own. Keeping both created
        # a confusing double-lock pattern (outer lock → inner SAVEPOINT → same
        # row locked twice by the same transaction) and a maintenance trap where
        # a reader might simplify apply_credit() back to non-locking form.
        # apply_credit() is self-contained; call it directly.
        try:
            ref.apply_credit()
            count += 1
        except Exception as exc:
            errors += 1
            _tasks_logger.exception(
                "apply_referral_credits: failed for referral %s: %s", ref.pk, exc
            )

    return f"Applied referral credits for {count} record(s). {errors} error(s)."


@shared_task
def refresh_fx_rates():
    """
    Runs periodically (hourly — see CELERY_BEAT_SCHEDULE). Fetches current
    EUR->ALL and USD->ALL rates from an external exchange-rate API and
    caches them via tenants.fx.set_rate() for create_booking_checkout to
    use when a customer chooses to pay in EUR or USD.

    Never raises: if the upstream API is unreachable or returns something
    unexpected, this just leaves the cache at its last-known value and
    returns without updating anything. There is no hardcoded fallback rate
    in tenants/fx.py any more — if the cache entry for a currency expires
    (see fx._CACHE_TTL_SECONDS) before this task successfully refreshes it
    again, that currency simply stops being offered at checkout
    (fx.is_available() returns False) rather than being quoted a stale or
    fabricated rate. A temporary outage here degrades to "EUR/USD payment
    temporarily unavailable, pay in ALL instead" — it never blocks ALL
    payments, which need no conversion.

    FX_RATE_API_URL is configurable via env var (see bizal/settings/base.py)
    in case the free upstream endpoint changes or an operator wants to
    swap in a different provider; the response is expected in the shape
    `{"rates": {"EUR": 0.0095, "USD": 0.0103, ...}}` — i.e. "1 ALL = X
    <currency>" — which this task inverts to the "ALL per unit" convention
    tenants/fx.py stores rates in.
    """
    from . import fx

    url = getattr(settings, 'FX_RATE_API_URL', '') or 'https://api.exchangerate-api.com/v4/latest/ALL'
    try:
        resp = requests.get(url, timeout=8)
        resp.raise_for_status()
        payload = resp.json()
        rates = payload.get('rates') or {}
    except Exception as exc:
        _tasks_logger.warning(
            "refresh_fx_rates: could not fetch rates from %s, keeping cached/fallback values: %s",
            url, exc,
        )
        return f"FX refresh failed ({exc}); kept cached/fallback rates."

    updated = []
    skipped = []
    for currency in fx.TRACKED_CURRENCIES:
        rate_from_all = rates.get(currency)
        if not rate_from_all:
            skipped.append(currency)
            continue
        try:
            rate_from_all = Decimal(str(rate_from_all))
            if rate_from_all <= 0:
                raise ValueError("non-positive rate")
            all_per_unit = (Decimal('1') / rate_from_all).quantize(Decimal('0.0001'))
            fx.set_rate(currency, all_per_unit)
            updated.append(currency)
        except Exception as exc:
            skipped.append(currency)
            _tasks_logger.warning(
                "refresh_fx_rates: bad rate for %s (%r), skipping: %s",
                currency, rate_from_all, exc,
            )

    return f"Refreshed FX rates: {', '.join(updated) or 'none'}. Skipped: {', '.join(skipped) or 'none'}."
