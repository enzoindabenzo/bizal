from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0002_add_webhook_event'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='payment',
            index=models.Index(fields=['stripe_session_id'], name='payments_stripe_session_id_idx'),
        ),
        migrations.AddConstraint(
            model_name='payment',
            constraint=models.UniqueConstraint(
                condition=~models.Q(stripe_session_id=''),
                fields=['stripe_session_id'],
                name='unique_stripe_session_id',
            ),
        ),
    ]
