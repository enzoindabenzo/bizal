from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0005_creditledger_nonzero_constraint'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenant',
            name='trial_warning_sent_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
