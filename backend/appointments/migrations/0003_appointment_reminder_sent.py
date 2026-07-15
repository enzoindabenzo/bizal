from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('appointments', '0002_appointment_tenant_date_status_idx'),
    ]

    operations = [
        migrations.AddField(
            model_name='appointment',
            name='reminder_sent',
            field=models.BooleanField(default=False),
        ),
    ]
