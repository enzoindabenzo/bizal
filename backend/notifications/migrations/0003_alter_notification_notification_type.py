# Generated for BizAL v14 — adds chatbot_handoff notification type

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0002_alter_notification_notification_type'),
    ]

    operations = [
        migrations.AlterField(
            model_name='notification',
            name='notification_type',
            field=models.CharField(
                choices=[
                    ('booking_confirmed', 'Booking Confirmed'),
                    ('booking_cancelled', 'Booking Cancelled'),
                    ('appointment_reminder', 'Appointment Reminder'),
                    ('appointment_new', 'New Appointment'),
                    ('order_placed', 'Order Placed'),
                    ('payment_success', 'Payment Successful'),
                    ('subscription_expiring', 'Subscription Expiring'),
                    ('new_review', 'New Review'),
                    ('new_contact', 'New Contact Message'),
                    ('chatbot_handoff', 'Chatbot Handoff'),
                    ('info', 'Info'),
                ],
                max_length=50,
            ),
        ),
    ]
