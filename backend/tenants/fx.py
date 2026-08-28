"""
FX conversion helpers.

ALL (Lek Shqiptar) is BizAL's single base/ledger currency — see the long
comment on Tenant.currency in tenants/models.py. Every price, total, and
stored amount anywhere on the platform (Booking.total_price/deposit_paid,
Payment.amount, invoices, referral credits, ...) is unconditionally ALL.

The ONLY place a foreign currency enters the picture is at the moment a
tenant's own customer pays: payments.views.create_booking_checkout lets
that customer choose to pay in EUR or USD instead of ALL — a payment
convenience aimed at tourists booking hotels, property/car/boat rentals,
who commonly expect to pay in their own currency even though ALL is the
legal ledger currency. This module converts an ALL amount into that
chosen currency at checkout time only. Nothing stored in the database is
ever denominated in EUR/USD; see payments/views.py and the Payment
metadata schema there for how the original ALL amount is preserved
alongside the charged currency/amount for refund accuracy.

Rates are cached as "ALL per 1 unit of foreign currency" (e.g. 105 ALL
per EUR) — the same convention a currency exchange office in Albania
would quote — and refreshed periodically by tenants.tasks.refresh_fx_rates
(see CELERY_BEAT_SCHEDULE in bizal/settings/base.py). There is
intentionally NO hardcoded fallback rate: if the cache is empty (fresh
deploy, first run before the periodic task has fired) or has expired
because refresh_fx_rates hasn't successfully run recently, that currency
is simply treated as unavailable — get_rate() raises RateUnavailable and
create_booking_checkout rejects it (see payments/views.py) rather than
silently charging a customer a rate that could be stale or fabricated.
ALL itself is always available since it needs no conversion.
"""
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from django.core.cache import cache

# Currencies tenants.tasks.refresh_fx_rates keeps a live cached rate for.
# ALL is always allowed on top of these (it's the ledger currency, so no
# conversion/rate is needed for it).
TRACKED_CURRENCIES = ('EUR', 'USD')

# Currencies a customer may choose to pay a booking deposit in. Note this
# is the *full candidate* list, not a guarantee of availability — EUR/USD
# are only actually offered at checkout time if a live rate is cached
# (see is_available() / get_available_pay_currencies() below).
SUPPORTED_PAY_CURRENCIES = ('ALL',) + TRACKED_CURRENCIES

_CACHE_KEY_PREFIX = 'fx_rate:'
# How long a fetched rate is trusted before it's treated as stale/expired.
# Shorter than it used to be now that there's no hardcoded floor to fall
# back on — we'd rather stop offering a currency than quote a rate that's
# gone unrefreshed for days. refresh_fx_rates runs hourly (see
# CELERY_BEAT_SCHEDULE), so this gives a couple of missed/slow runs of
# slack before the currency drops out.
_CACHE_TTL_SECONDS = 60 * 60 * 3


class UnsupportedCurrency(ValueError):
    """Raised when a currency outside SUPPORTED_PAY_CURRENCIES is requested."""


class RateUnavailable(RuntimeError):
    """
    Raised when a live rate isn't cached for a requested currency — e.g.
    refresh_fx_rates hasn't run yet, has been failing, or the API has been
    unreachable long enough for the cached rate to expire. There is no
    hardcoded fallback to fall through to; callers (create_booking_checkout)
    should treat this as "don't offer this currency right now", not retry
    with a guessed rate.
    """


def is_available(currency):
    """
    True if a live cached rate currently exists for `currency` ('EUR' or
    'USD'). ALL is not a valid argument here — it's always available by
    definition and has no rate.
    """
    currency = (currency or '').upper()
    if currency not in TRACKED_CURRENCIES:
        return False
    cached = cache.get(f'{_CACHE_KEY_PREFIX}{currency}')
    if cached is None:
        return False
    try:
        return Decimal(str(cached)) > 0
    except (InvalidOperation, ValueError, TypeError):
        return False


def get_available_pay_currencies():
    """
    Return the list of currencies a customer can actually pay with right
    now: 'ALL' always, plus whichever of TRACKED_CURRENCIES currently has
    a live cached rate. Used by the public available-currencies endpoint
    and by create_booking_checkout's validation.
    """
    return ['ALL'] + [c for c in TRACKED_CURRENCIES if is_available(c)]


def get_rate(currency):
    """
    Return the current Decimal rate, expressed as ALL per 1 unit of
    `currency` (must be 'EUR' or 'USD' — not 'ALL', which has no rate by
    definition). Reads the Celery-refreshed cache value.

    Raises RateUnavailable if no live rate is cached — there is no
    hardcoded floor to fall back to.
    """
    currency = (currency or '').upper()
    if currency not in TRACKED_CURRENCIES:
        raise UnsupportedCurrency(f"No FX rate available for currency {currency!r}.")

    cached = cache.get(f'{_CACHE_KEY_PREFIX}{currency}')
    if cached is not None:
        try:
            rate = Decimal(str(cached))
            if rate > 0:
                return rate
        except (InvalidOperation, ValueError, TypeError):
            pass  # treat as unavailable below

    raise RateUnavailable(
        f"No live FX rate is currently cached for {currency}; "
        f"refresh_fx_rates hasn't populated it yet or the cached value has expired."
    )


def set_rate(currency, rate_all_per_unit):
    """
    Cache a freshly-fetched rate. Called only by
    tenants.tasks.refresh_fx_rates after a successful upstream fetch.
    """
    currency = (currency or '').upper()
    if currency not in TRACKED_CURRENCIES:
        raise UnsupportedCurrency(f"Cannot set FX rate for unsupported currency {currency!r}.")
    rate_all_per_unit = Decimal(str(rate_all_per_unit))
    if rate_all_per_unit <= 0:
        raise ValueError(f"Refusing to cache a non-positive FX rate for {currency}: {rate_all_per_unit}")
    cache.set(f'{_CACHE_KEY_PREFIX}{currency}', str(rate_all_per_unit), _CACHE_TTL_SECONDS)


def convert_all_to(amount_all, currency):
    """
    Convert a Decimal (or decimal-castable) ALL amount into `currency`
    ('ALL', 'EUR', or 'USD'). Returns a Decimal rounded to 2 decimal
    places — every currency offered here is a 2-decimal currency for
    Stripe's purposes, so unit_amount = result * 100 is always exact cents.

    Raises RateUnavailable (not UnsupportedCurrency) if `currency` is a
    tracked currency but no live rate is currently cached for it — callers
    should catch this and reject/hide that payment option rather than
    silently converting.
    """
    currency = (currency or 'ALL').upper()
    if currency not in SUPPORTED_PAY_CURRENCIES:
        raise UnsupportedCurrency(f"{currency!r} is not a supported payment currency.")

    amount_all = Decimal(str(amount_all))
    if currency == 'ALL':
        return amount_all.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    rate = get_rate(currency)  # ALL per 1 unit of `currency`; may raise RateUnavailable
    converted = amount_all / rate
    return converted.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def convert_to_all(amount, currency):
    """
    Inverse of convert_all_to — used when reconciling a refund: given an
    amount already charged in a foreign currency, work out its ALL
    equivalent (e.g. to validate a partial-refund request against the
    original ALL-denominated Payment.amount).
    """
    currency = (currency or 'ALL').upper()
    if currency not in SUPPORTED_PAY_CURRENCIES:
        raise UnsupportedCurrency(f"{currency!r} is not a supported payment currency.")

    amount = Decimal(str(amount))
    if currency == 'ALL':
        return amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    rate = get_rate(currency)
    return (amount * rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
