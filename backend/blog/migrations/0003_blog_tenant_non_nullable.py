"""
Make BlogPost.tenant and BlogTag.tenant non-nullable.

The nullable FK was introduced in 0002 to allow a hypothetical
main-platform blog with no tenant. That feature is not wired up and the
nullable FK allows orphaned rows that bypass the CASCADE guarantee.
Reverting to non-nullable is safe as long as there are no null-tenant rows
in the database. The migration will fail (intentionally) if there are any,
forcing you to assign or delete them first.

If a main-platform blog is genuinely needed in the future, add a
PlatformBlogPost model in blog/platform_models.py following the pattern in
reviews/platform_models.py — do not re-introduce a nullable tenant FK.
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0003_tenant_v3_expansion'),
        ('blog', '0002_alter_blogpost_tenant_alter_blogtag_tenant'),
    ]

    operations = [
        migrations.AlterField(
            model_name='blogpost',
            name='tenant',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='blog_%(app_label)s_%(class)s_set',
                to='tenants.tenant',
            ),
        ),
        migrations.AlterField(
            model_name='blogtag',
            name='tenant',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='blog_tags',
                to='tenants.tenant',
            ),
        ),
    ]
