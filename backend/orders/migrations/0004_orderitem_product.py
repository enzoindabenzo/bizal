from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0003_order_delivery_address'),
        ('inventory', '0004_product_low_stock_threshold'),
    ]

    operations = [
        migrations.AlterField(
            model_name='orderitem',
            name='menu_item',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                to='menu.menuitem',
            ),
        ),
        migrations.AddField(
            model_name='orderitem',
            name='product',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name='order_items', to='inventory.product',
            ),
        ),
        migrations.AddConstraint(
            model_name='orderitem',
            constraint=models.CheckConstraint(
                check=models.Q(('menu_item__isnull', False), ('product__isnull', True)) |
                      models.Q(('menu_item__isnull', True), ('product__isnull', False)),
                name='orderitem_exactly_one_of_menu_item_or_product',
            ),
        ),
    ]
