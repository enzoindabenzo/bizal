# Generated 2026-06-25 — LOW-5 fix: add reminder_attempts counter

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bookings', '0003_booking_reminder_sent'),
    ]

    operations = [
        migrations.AddField(
            model_name='booking',
            name='reminder_attempts',
            field=models.PositiveSmallIntegerField(default=0),
        ),
    ]
