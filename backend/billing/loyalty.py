"""
BizAL — Loyalty points accrual.

Centralises the "when does a customer earn points" logic so both the
orders app and the bookings app can call into it without duplicating the
feature-flag check, idempotency guard, or point calculation.
"""
from .models import LoyaltyAccount, LoyaltyTransaction, POINTS_PER_CURRENCY_UNIT


def _already_awarded(tenant, source_type, source_id):
    return LoyaltyTransaction.objects.filter(
        tenant=tenant, source_type=source_type, source_id=str(source_id), points__gt=0,
    ).exists()


def award_points(tenant, user, amount_spent, *, reason, source_type, source_id):
    """
    Credit loyalty points to `user` for `tenant` based on `amount_spent`.

    No-ops (silently) when:
      - the tenant doesn't have loyalty_program enabled,
      - there's no authenticated user (guest checkout — nothing to credit),
      - amount_spent isn't positive,
      - points were already awarded for this exact source (re-running the
        same status transition, e.g. completed -> completed via a retried
        request, must not double-credit).
    """
    if not tenant or not tenant.has_feature('loyalty_program'):
        return None
    if not user or not getattr(user, 'is_authenticated', False):
        return None
    try:
        # MED-4 FIX: Use Decimal arithmetic instead of float() to avoid precision
        # errors on Decimal loyalty amounts. float(Decimal('9.99')) can produce
        # 9.989999999999... which rounds down to fewer points than expected.
        from decimal import Decimal, InvalidOperation
        amount_spent = Decimal(str(amount_spent or 0))
    except (TypeError, ValueError, InvalidOperation):
        return None
    if amount_spent <= 0:
        return None
    if _already_awarded(tenant, source_type, source_id):
        return None

    points = int(amount_spent * POINTS_PER_CURRENCY_UNIT)  # Decimal * Decimal stays exact
    if points <= 0:
        return None

    # MED-3 FIX (v36): wrap get_or_create in atomic() so Django's internal
    # retry on IntegrityError (from the unique_together on LoyaltyAccount)
    # works correctly. Outside a transaction, a concurrent first-time award
    # for the same (tenant, user) pair causes one of the two callers to
    # receive an unhandled IntegrityError instead of getting the existing row.
    #
    # v49 FIX: catch IntegrityError from the UniqueConstraint on LoyaltyTransaction
    # (tenant, source_type, source_id, points__gt=0). Two concurrent requests that
    # both pass the _already_awarded() pre-check (TOCTOU race — the check is outside
    # this atomic block) can both reach account.add_points(), but only the first
    # LoyaltyTransaction.objects.create() will succeed; the second raises
    # IntegrityError. The constraint is doing its job — no double-credit occurs —
    # so the second caller should silently succeed rather than propagate an unhandled
    # 500. The migration comment that said "the caller handles this cleanly" was wrong;
    # this catch is the fix that makes that claim true.
    from django.db import transaction, IntegrityError
    try:
        with transaction.atomic():
            account, _ = LoyaltyAccount.objects.get_or_create(tenant=tenant, user=user)
            account.add_points(points, reason=reason, source_type=source_type, source_id=source_id)
    except IntegrityError:
        # Second concurrent call for the same source — award already recorded by
        # the first caller. Return the existing account without raising.
        account = LoyaltyAccount.objects.filter(tenant=tenant, user=user).first()
    return account
