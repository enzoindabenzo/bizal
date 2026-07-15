"""
HIGH-1 FIX (v36): Add UniqueConstraint to LoyaltyTransaction to prevent
double-award race condition. Two concurrent webhook retries / order-complete
calls can both pass the _already_awarded() exists() check before either
commits, resulting in two award rows for the same source event. The DB
constraint makes the second INSERT fail with IntegrityError — the caller
(award_points() wrapped in atomic()) handles this cleanly.

Filtered to points__gt=0 (award rows only) and non-empty source_type/source_id
so manual/no-source redemption entries are not constrained.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0004_loyaltyaccount_loyaltytransaction'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='loyaltytransaction',
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    points__gt=0,
                    source_type__gt='',
                    source_id__gt='',
                ),
                fields=['tenant', 'source_type', 'source_id'],
                name='unique_loyalty_award_per_source',
            ),
        ),
    ]
