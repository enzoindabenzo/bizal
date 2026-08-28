# Generated manually on 2026-06-30
#
# Fixes the cross-tenant registration/login bug: email used to be globally
# unique on the User model, so a customer who already had an account on one
# tenant could never register on another tenant's portal with the same email
# ("Ka tashmë një user me këtë email"), and — once that error pushed them to
# log in instead — login failed too ("Invalid credentials for this portal")
# because their only existing account belonged to a different tenant.
#
# Email uniqueness is now scoped to (email, tenant) instead of being global.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0005_add_email_verified'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='email',
            field=models.EmailField(max_length=254),
        ),
        migrations.AddConstraint(
            model_name='user',
            constraint=models.UniqueConstraint(
                fields=('email', 'tenant'),
                name='accounts_user_unique_email_per_tenant',
            ),
        ),
    ]
