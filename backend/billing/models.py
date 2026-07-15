from decimal import Decimal
from django.db import models
from django.db.models import functions as db_functions
from bizal.base_models import TenantScopedUUIDModel

INVOICE_STATUS = [
    ('draft', 'Draft'),
    ('sent', 'Sent'),
    ('paid', 'Paid'),
    ('overdue', 'Overdue'),
    ('cancelled', 'Cancelled'),
]

# Points earned per 1 unit of the tenant's local currency spent on a
# completed order/booking. Kept as a single platform-wide constant for now
# (no per-tenant override exists yet) — see LoyaltyAccount.point_value for
# the inverse conversion used when displaying a € estimate to the customer.
POINTS_PER_CURRENCY_UNIT = Decimal('0.1')   # e.g. 1000 ALL spent -> 100 points
POINT_VALUE_IN_EUR = 0.01        # 100 points ≈ €1.00, shown to the customer


class LoyaltyAccount(TenantScopedUUIDModel):
    """One row per (tenant, customer) — running points balance.

    Created lazily the first time a customer earns or checks their points
    for a given tenant, rather than for every signup, since most tenants
    don't have loyalty_program enabled at all.
    """
    user = models.ForeignKey(
        'accounts.User', on_delete=models.CASCADE, related_name='loyalty_accounts'
    )
    points = models.PositiveIntegerField(default=0)
    lifetime_points = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ('tenant', 'user')

    def __str__(self):
        return f"{self.user.email} @ {self.tenant.slug}: {self.points} pts"

    def add_points(self, amount, reason, source_type='', source_id=''):
        """Credit points and record a ledger entry. amount may be negative
        for redemptions; lifetime_points only ever increases (it tracks
        points ever earned, not the current balance).

        CRIT-2 / MED-3 FIX: use select_for_update() + F() expressions inside
        an atomic block to prevent the read-modify-write race where two
        concurrent requests both read the same stale balance and overwrite each
        other's increment.  The LoyaltyTransaction is created inside the same
        transaction so the ledger is never out of sync with the balance.
        """
        if amount == 0:
            return
        from django.db import transaction
        from django.db.models import F
        with transaction.atomic():
            # Lock this row for the duration of the transaction.
            LoyaltyAccount.objects.select_for_update().filter(pk=self.pk).update(
                points=F('points') + amount if amount >= 0
                       else db_functions.Greatest(F('points') + amount, 0),
                lifetime_points=(F('lifetime_points') + amount
                                 if amount > 0 else F('lifetime_points')),
            )
            # Refresh so self.points / self.lifetime_points reflect the new DB value.
            self.refresh_from_db(fields=['points', 'lifetime_points'])
            LoyaltyTransaction.objects.create(
                tenant=self.tenant, account=self, points=amount, reason=reason,
                source_type=source_type, source_id=str(source_id or ''),
            )


class LoyaltyTransaction(TenantScopedUUIDModel):
    """Ledger entry for a single points credit/debit — powers the
    customer-facing history list on the account page."""
    account = models.ForeignKey(
        LoyaltyAccount, on_delete=models.CASCADE, related_name='transactions'
    )
    points = models.IntegerField()  # positive = earned, negative = redeemed
    reason = models.CharField(max_length=200, blank=True)
    # Loosely-typed reference back to the order/booking that triggered this
    # entry (no FK, since either model could be the source and either could
    # later be deleted without invalidating loyalty history).
    source_type = models.CharField(max_length=20, blank=True)  # 'order' | 'booking' | 'manual'
    source_id = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            # HIGH-1 FIX (v36): Prevent double-award race. Two concurrent webhook
            # retries / order-complete calls can both pass the _already_awarded()
            # exists() check before either commits, producing two LoyaltyTransaction
            # rows for the same source event. This unique constraint makes the DB
            # the final arbiter — the second INSERT raises IntegrityError.
            # Filtered to points__gt=0 (award rows only) so redemptions against
            # the same source are not blocked. source_type/source_id must be
            # non-empty so manual/no-source entries don't collide.
            models.UniqueConstraint(
                fields=['tenant', 'source_type', 'source_id'],
                condition=models.Q(points__gt=0, source_type__gt='', source_id__gt=''),
                name='unique_loyalty_award_per_source',
            ),
        ]

    def __str__(self):
        sign = '+' if self.points >= 0 else ''
        return f"{sign}{self.points} pts — {self.reason}"


class Invoice(TenantScopedUUIDModel):
    """Manual invoices a tenant can issue to their own customers."""
    customer = models.ForeignKey(
        'accounts.User', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='invoices'
    )
    customer_name = models.CharField(max_length=200, blank=True)
    customer_email = models.EmailField(blank=True)
    invoice_number = models.CharField(max_length=60, blank=True)
    status = models.CharField(max_length=20, choices=INVOICE_STATUS, default='draft')
    issued_date = models.DateField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    # Persisted total so invoices can be sorted/aggregated in the DB without
    # loading all lines into Python.  Kept in sync by recompute_total(), which
    # InvoiceLineSerializer calls after every line create/update/delete.
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Invoice {self.invoice_number or self.pk} — {self.get_status_display()}"

    @property
    def total(self):
        # Still available as a property for templates/serializers that use it,
        # but backed by the persisted field when lines are already prefetched.
        # For fresh calculations (e.g. after a line is added), call
        # recompute_total() explicitly.
        return self.total_amount

    def recompute_total(self):
        """Recompute and persist the invoice total from its lines."""
        computed = sum(line.amount for line in self.lines.all())
        Invoice.objects.filter(pk=self.pk).update(total_amount=computed)
        self.total_amount = computed


class InvoiceLine(TenantScopedUUIDModel):
    """
    NOTE: `save()` below keeps the parent Invoice's `total_amount` in sync
    on every line save/delete. This relies on save()/delete() actually
    running — Django's `InvoiceLine.objects.bulk_create([...])` bypasses
    both, so any future bulk-insert of lines MUST be followed by an
    explicit `invoice.recompute_total()` call, or `total_amount` will go
    stale. No `bulk_create` usage exists in this codebase today, but this
    is a real footgun for anyone adding one later.
    """
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='lines')
    description = models.CharField(max_length=300)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)

    @property
    def amount(self):
        return self.quantity * self.unit_price

    def save(self, *args, **kwargs):
        # M-5 FIX: previously this called super().save() then
        # self.invoice.recompute_total() with no transaction around the
        # pair. Two InvoiceLine saves for the same invoice arriving close
        # together (e.g. a bulk import POSTing two lines back-to-back)
        # could each read self.lines.all() before the other's row was
        # committed, then both UPDATE total_amount — the second UPDATE
        # silently overwrites the first with a total that's missing a
        # line. select_for_update() on the parent Invoice row serialises
        # the read-recompute-write sequence across concurrent line saves:
        # the second transaction blocks until the first commits, so it
        # always recomputes from the fully up-to-date line set.
        from django.db import transaction
        with transaction.atomic():
            super().save(*args, **kwargs)
            locked_invoice = Invoice.objects.select_for_update().get(pk=self.invoice_id)
            locked_invoice.recompute_total()
            self.invoice = locked_invoice

    def delete(self, *args, **kwargs):
        from django.db import transaction
        with transaction.atomic():
            invoice_id = self.invoice_id
            super().delete(*args, **kwargs)
            locked_invoice = Invoice.objects.select_for_update().get(pk=invoice_id)
            locked_invoice.recompute_total()

    def __str__(self):
        return f"{self.description} x{self.quantity}"
