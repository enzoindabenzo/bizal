from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0004_creditledger'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='creditledger',
            constraint=models.CheckConstraint(
                check=~models.Q(amount=0),
                name='credit_ledger_nonzero_amount',
            ),
        ),
    ]
