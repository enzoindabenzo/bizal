"""
Migration: BizAL Tenant v3 expansion
  - New business types (29 → 50)
  - New plan: trial
  - New fields: latitude, longitude, referral_code, referred_by,
                referral_credits, listed_on_marketplace, marketplace_description
  - TenantFeature: is_custom_grant field
  - New models: TenantLocation, TenantReferral
"""
import uuid
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0002_tenant_onboarding_complete_tenant_onboarding_step'),
    ]

    operations = [
        # ── Update plan choices to include trial ──────────────────────────────
        migrations.AlterField(
            model_name='tenant',
            name='plan',
            field=models.CharField(
                choices=[
                    ('trial', 'Trial (14 days)'),
                    ('starter', 'Starter'),
                    ('pro', 'Pro'),
                    ('enterprise', 'Enterprise'),
                ],
                default='trial',
                max_length=20,
            ),
        ),

        # ── Update business_type choices ──────────────────────────────────────
        migrations.AlterField(
            model_name='tenant',
            name='business_type',
            field=models.CharField(
                choices=[
                    ('market', 'Market / General Shop'), ('pharmacy', 'Pharmacy'),
                    ('electronics', 'Electronics Store'), ('clothing', 'Clothing Store'),
                    ('organic', 'Organic Market'), ('bookstore', 'Bookstore / Stationery'),
                    ('jewelry', 'Jewelry & Accessories'), ('toy_store', 'Toy & Baby Store'),
                    ('sports_shop', 'Sports & Outdoors Shop'), ('furniture', 'Furniture & Home Decor'),
                    ('petrol_station', 'Petrol Station'),
                    ('restaurant', 'Restaurant / Café'), ('hotel', 'Hotel / Guesthouse'),
                    ('bar', 'Bar / Night Club'), ('delivery_kitchen', 'Food Delivery Kitchen'),
                    ('bakery', 'Bakery & Patisserie'), ('catering', 'Catering Service'),
                    ('car_rental', 'Car Rental'), ('property_rental', 'Property Rental'),
                    ('equipment_rental', 'Equipment Rental'), ('boat_rental', 'Boat Rental'),
                    ('barbershop', 'Barbershop / Hair Salon'), ('spa', 'Spa & Wellness'),
                    ('gym', 'Gym / Fitness Studio'), ('clinic', 'Clinic / Dental'),
                    ('tattoo', 'Tattoo Studio'), ('veterinary', 'Veterinary Clinic'),
                    ('optician', 'Optician'),
                    ('auto_repair', 'Auto Repair'), ('cleaning', 'Cleaning Service'),
                    ('lawyer', 'Lawyer / Notary'), ('accounting', 'Accounting Firm'),
                    ('event_agency', 'Event Agency'), ('photography', 'Photography Studio'),
                    ('printing', 'Print & Design Studio'), ('travel_agency', 'Travel Agency'),
                    ('funeral_home', 'Funeral Home'), ('security', 'Security Company'),
                    ('language_school', 'Language School'), ('tutoring', 'Tutoring Centre'),
                    ('driving_school', 'Driving School'), ('coding_bootcamp', 'Coding Bootcamp'),
                    ('nursery', 'Nursery / Childcare'),
                    ('real_estate', 'Real Estate Agency'), ('construction', 'Construction / Contractor'),
                    ('architecture', 'Architecture & Design Firm'),
                    ('import_export', 'Import / Export Company'),
                    ('agro', 'Agricultural Supplier'), ('transport', 'Transport & Logistics'),
                    ('it_company', 'IT Company'), ('marketing_agency', 'Marketing Agency'),
                ],
                default='restaurant',
                max_length=50,
            ),
        ),

        # ── New Tenant fields ─────────────────────────────────────────────────
        migrations.AddField(
            model_name='tenant', name='latitude',
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True),
        ),
        migrations.AddField(
            model_name='tenant', name='longitude',
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True),
        ),
        migrations.AddField(
            model_name='tenant', name='referral_code',
            field=models.CharField(blank=True, max_length=20, unique=True, default=''),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='tenant', name='referred_by',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='referrals', to='tenants.tenant',
            ),
        ),
        migrations.AddField(
            model_name='tenant', name='referral_credits',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=8),
        ),
        migrations.AddField(
            model_name='tenant', name='listed_on_marketplace',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='tenant', name='marketplace_description',
            field=models.TextField(blank=True),
        ),

        # ── TenantFeature: custom grant flag ──────────────────────────────────
        migrations.AddField(
            model_name='tenantfeature', name='is_custom_grant',
            field=models.BooleanField(default=False),
        ),

        # ── TenantLocation model ──────────────────────────────────────────────
        migrations.CreateModel(
            name='TenantLocation',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True)),
                ('tenant', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='locations', to='tenants.tenant',
                )),
                ('name',       models.CharField(max_length=200)),
                ('address',    models.CharField(blank=True, max_length=300)),
                ('city',       models.CharField(blank=True, max_length=100)),
                ('phone',      models.CharField(blank=True, max_length=30)),
                ('email',      models.EmailField(blank=True)),
                ('latitude',   models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
                ('longitude',  models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
                ('is_primary', models.BooleanField(default=False)),
                ('is_active',  models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={'ordering': ['-is_primary', 'name']},
        ),

        # ── TenantReferral model ──────────────────────────────────────────────
        migrations.CreateModel(
            name='TenantReferral',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True)),
                ('referrer', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='referral_records', to='tenants.tenant',
                )),
                ('referred', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='referral_source', to='tenants.tenant',
                )),
                ('credit_eur', models.DecimalField(decimal_places=2, default=10.0, max_digits=6)),
                ('applied',    models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
        ),
    ]
