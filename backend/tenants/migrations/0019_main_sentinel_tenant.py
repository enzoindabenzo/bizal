from django.db import migrations


MAIN_TENANT_SLUG = "main"


def create_main_tenant(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    if Tenant.objects.filter(slug=MAIN_TENANT_SLUG).exists():
        return
    Tenant.objects.create(
        name="Main",
        slug=MAIN_TENANT_SLUG,
        business_type="it_company",
        plan="enterprise",
        is_active=True,
        country="Albania",
    )


def remove_main_tenant(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    Tenant.objects.filter(slug=MAIN_TENANT_SLUG).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0018_rename_credit_eur_to_credit_amount"),
    ]

    operations = [
        migrations.RunPython(create_main_tenant, remove_main_tenant),
    ]
