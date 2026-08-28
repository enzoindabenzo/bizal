"""
Add CreditLedger model for referral credit audit trail.

Also adds a CreditLedger creation call inside TenantReferral.apply_credit()
(handled in models.py — no schema change needed there).
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0003_tenant_v3_expansion'),
    ]

    operations = [
        migrations.CreateModel(
            name='CreditLedger',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('amount', models.DecimalField(decimal_places=2, max_digits=8)),
                ('event', models.CharField(
                    choices=[
                        ('referral',   'Referral earned'),
                        ('redemption', 'Redeemed against invoice'),
                        ('adjustment', 'Manual adjustment'),
                    ],
                    max_length=20,
                )),
                ('description', models.CharField(blank=True, max_length=300)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('tenant', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='credit_ledger',
                    to='tenants.tenant',
                )),
                ('referral', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='ledger_entries',
                    to='tenants.tenantreferral',
                )),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
