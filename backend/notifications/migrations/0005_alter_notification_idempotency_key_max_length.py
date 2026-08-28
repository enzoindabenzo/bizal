# MED-5 FIX — see notifications/models.py.
#
# Increases idempotency_key max_length from 120 to 200 characters to provide
# headroom for composite keys like 'appointment_reminder_{tenant_slug}_{id}'.
# At 120 chars, callers with longer prefixes could silently truncate on some
# DB engine modes, causing false uniqueness collisions or missed deduplication.
# This is a non-destructive ALTER COLUMN on PostgreSQL (no data rewrite needed
# when increasing VARCHAR length without crossing the 255-byte threshold).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0004_notification_idempotency_key'),
    ]

    operations = [
        migrations.AlterField(
            model_name='notification',
            name='idempotency_key',
            field=models.CharField(blank=True, default='', max_length=200),
        ),
    ]
