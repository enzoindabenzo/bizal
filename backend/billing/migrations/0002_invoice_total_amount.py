"""
Add Invoice.total_amount — a persisted decimal column so invoices can be
sorted and aggregated in the DB without fetching all InvoiceLine rows into
Python. Replaces the Python-only `total` property that caused N+1 queries
on any list view that didn't prefetch 'lines'.

The column defaults to 0 on existing rows. Run a one-off management command
(or the `recompute_invoice_totals` task stub below) to backfill production
data after deploying this migration.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoice',
            name='total_amount',
            field=models.DecimalField(
                max_digits=12,
                decimal_places=2,
                default=0,
                help_text='Persisted sum of all invoice lines. Kept in sync by InvoiceLine.save/delete.',
            ),
        ),
    ]
