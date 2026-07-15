# Generated manually — renames TenantReferral.credit_eur to credit_amount.
#
# Referral credits, like every other stored amount on the platform, are
# denominated in ALL (Lek) — see the Tenant.currency comment and
# tenants/fx.py's module docstring. The old "_eur" name was legacy/
# misleading, not a real currency distinction, and had the tenant admin
# frontend rendering it with a "€" prefix next to figures that were
# actually Lek. RenameField preserves existing data; no data migration
# needed.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0017_lock_currency_to_all'),
    ]

    operations = [
        migrations.RenameField(
            model_name='tenantreferral',
            old_name='credit_eur',
            new_name='credit_amount',
        ),
    ]
