# Generated 2026-06-25 — LOW-5 fix: add reminder_attempts counter

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('appointments', '0005_sync_image_validators'),
    ]

    operations = [
        migrations.AddField(
            model_name='appointment',
            name='reminder_attempts',
            field=models.PositiveSmallIntegerField(default=0),
        ),
    ]
