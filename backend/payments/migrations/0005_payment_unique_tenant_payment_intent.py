from django.db import migrations, models


class Migration(migrations.Migration):
    """
    L-2 FIX: Add a partial unique constraint on (tenant, stripe_payment_intent)
    when stripe_payment_intent is non-empty.  This gives the DB-level guarantee
    that update_or_create() in the invoice.payment_failed webhook handler needs
    to remain idempotent even when the Redis idempotency cache is evicted
    between concurrent Stripe retries.
    """

    dependencies = [
        ('payments', '0004_remove_webhookevent_broken_constraint'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='payment',
            constraint=models.UniqueConstraint(
                condition=~models.Q(stripe_payment_intent=''),
                fields=['tenant', 'stripe_payment_intent'],
                name='unique_tenant_payment_intent',
            ),
        ),
    ]
