# Generated manually: removes the StorefrontSection model. The drag-and-drop
# homepage builder ("Vitrina" > Ndërtuesi i Faqes) has been removed from the
# tenant admin UI; this table and its API are no longer used.
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('storefront', '0003_storefrontsection'),
    ]

    operations = [
        migrations.DeleteModel(
            name='StorefrontSection',
        ),
    ]
