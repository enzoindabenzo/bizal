from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('appointments', '0001_initial'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='appointment',
            index=models.Index(
                fields=['tenant', 'date', 'status'],
                name='appt_tenant_date_status_idx',
            ),
        ),
    ]
