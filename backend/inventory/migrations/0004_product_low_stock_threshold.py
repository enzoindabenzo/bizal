from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0003_sync_image_validators'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='low_stock_threshold',
            field=models.PositiveIntegerField(
                default=5,
                help_text='Stock at or below this level is flagged as low stock in the admin.',
            ),
        ),
        migrations.AlterField(
            model_name='product',
            name='category',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=models.SET_NULL,
                related_name='products', to='inventory.productcategory',
            ),
        ),
    ]
