# Generated manually — see blog/models.py BlogPost.status for rationale.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('blog', '0005_sync_image_validators'),
    ]

    operations = [
        migrations.AlterField(
            model_name='blogpost',
            name='status',
            field=models.CharField(
                max_length=20,
                choices=[('draft', 'Draft'), ('published', 'Published'), ('archived', 'Archived')],
                default='published',
            ),
        ),
    ]
