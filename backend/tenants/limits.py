"""
Shared plan-limit enforcement helpers.

`enforce_max_listings` mirrors the max_staff enforcement pattern already
used in staff/views.py (see StaffInviteView): the Tenant row itself is
locked with select_for_update() before counting, because SELECT FOR UPDATE
on a COUNT() only locks rows that already exist — it cannot block a
concurrent INSERT of a new row that doesn't exist yet (the classic
Postgres phantom-insert gap). Locking the always-existing Tenant row
serializes concurrent create attempts for this tenant through a single
lock, closing the race entirely.

Callers MUST call this inside the same `transaction.atomic()` block that
performs the eventual INSERT, and must not release the lock in between —
otherwise two concurrent requests can both pass the check and both insert,
exceeding the plan's max_listings cap.

Usage (inside perform_create, already wrapped in transaction.atomic() by
the caller — or perform_create itself opens the atomic block):

    from tenants.limits import enforce_max_listings
    from django.db import transaction

    def perform_create(self, serializer):
        with transaction.atomic():
            enforce_max_listings(self.request.tenant, RoomType)
            serializer.save(tenant=self.request.tenant)
"""
from django.db import transaction
from rest_framework.exceptions import PermissionDenied


def enforce_max_listings(tenant, model_cls, extra_filter=None):
    """
    Raise PermissionDenied if creating one more `model_cls` row for `tenant`
    would exceed the tenant's plan 'max_listings' limit.

    `model_cls` must have a `tenant` FK/field. `extra_filter` is an optional
    dict of additional filter kwargs (e.g. to scope the count to a subset).

    Each listing type (RoomType, Room, RentalItem, Product, MenuItem,
    Service, ...) is counted independently against the same cap — a tenant
    can have up to `max_listings` RoomTypes AND, separately, up to
    `max_listings` Rooms. This matches the existing product behavior where
    each vertical's inventory is capped independently per plan.
    """
    from tenants.models import Tenant as TenantModel

    # Lock the Tenant row so concurrent create requests for this tenant are
    # serialized through this single point, closing the phantom-insert race.
    TenantModel.objects.select_for_update().get(pk=tenant.pk)

    limit = tenant.get_limit('max_listings')
    if not limit:
        # 0 or unset means "no cap configured" — fail open rather than
        # blocking every tenant whose plan is missing the key.
        return

    filters = {'tenant': tenant}
    if extra_filter:
        filters.update(extra_filter)
    current_count = model_cls.objects.filter(**filters).count()

    if current_count >= limit:
        raise PermissionDenied(
            f'Listing limit reached for your plan ({limit}). '
            f'Upgrade your plan to add more.'
        )
