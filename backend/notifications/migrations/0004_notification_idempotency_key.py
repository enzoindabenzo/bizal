# M-3 FIX — see notifications/models.py and notifications/utils.py.
#
# Adds Notification.idempotency_key (blank by default, so every existing
# caller that never passes one is completely unaffected) plus a conditional
# unique constraint so that notify_owner()/notify_owner_async() retries that
# DO pass a stable key no longer create duplicate in-app notifications for
# the same source event.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0003_alter_notification_notification_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='notification',
            name='idempotency_key',
            field=models.CharField(blank=True, default='', max_length=120),
        ),
        migrations.AddConstraint(
            model_name='notification',
            constraint=models.UniqueConstraint(
                condition=~models.Q(idempotency_key=''),
                fields=('tenant', 'user', 'notification_type', 'idempotency_key'),
                name='uniq_notification_idempotency_key',
            ),
        ),
    ]
