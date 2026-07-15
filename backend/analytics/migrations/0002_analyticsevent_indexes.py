from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('analytics', '0001_initial'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='analyticsevent',
            index=models.Index(fields=['tenant', 'event_type'], name='analytics_tenant_evtype_idx'),
        ),
        migrations.AddIndex(
            model_name='analyticsevent',
            index=models.Index(fields=['tenant', '-created_at'], name='analytics_tenant_created_idx'),
        ),
    ]
