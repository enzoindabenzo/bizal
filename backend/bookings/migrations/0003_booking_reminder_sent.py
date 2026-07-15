from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Add reminder_sent to Booking so the send_booking_reminders Celery task
    can mark a booking as reminded and avoid re-sending every hour.
    """

    dependencies = [
        ('bookings', '0002_booking_composite_indexes'),
    ]

    operations = [
        migrations.AddField(
            model_name='booking',
            name='reminder_sent',
            field=models.BooleanField(default=False),
        ),
    ]
