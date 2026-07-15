from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ('orders', '0002_alter_order_tenant'),
    ]
    operations = [
        migrations.AddField(
            model_name='order',
            name='delivery_address',
            field=models.CharField(blank=True, max_length=300),
        ),
    ]