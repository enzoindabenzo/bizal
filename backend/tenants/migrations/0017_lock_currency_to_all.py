# Generated manually — locks Tenant.currency to ALL as the platform's single
# base/ledger currency. See the long comment on Tenant.currency in
# tenants/models.py for the full rationale.

from django.db import migrations, models


def normalize_existing_currency_to_all(apps, schema_editor):
    """
    Data migration: any tenant previously set to EUR or USD (back when
    currency was tenant-selectable) gets normalized to ALL. This does NOT
    touch anything about how that tenant's customers pay — EUR/USD
    checkout is still available via the pay_currency choice at Stripe
    checkout time (payments/views.py). This only fixes the *ledger*
    currency, which must be ALL platform-wide.
    """
    Tenant = apps.get_model('tenants', 'Tenant')
    Tenant.objects.exclude(currency='ALL').update(currency='ALL')


def noop_reverse(apps, schema_editor):
    # Deliberately a no-op: reversing this migration should not resurrect
    # EUR/USD as a tenant-selectable ledger currency, since we no longer
    # know which tenants originally had which value.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0016_tenant_accepts_online_payments'),
    ]

    operations = [
        migrations.RunPython(normalize_existing_currency_to_all, noop_reverse),
        migrations.AlterField(
            model_name='tenant',
            name='currency',
            field=models.CharField(
                choices=[('ALL', 'Lek Shqiptar (ALL)')],
                default='ALL',
                max_length=3,
            ),
        ),
    ]
