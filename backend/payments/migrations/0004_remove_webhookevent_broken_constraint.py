"""
CRIT-1 FIX: Remove the broken UniqueConstraint from WebhookEvent.Meta.

The WebhookEvent model had a copy-pasted constraints block from Payment.Meta
that referenced `stripe_session_id` — a field that does not exist on
WebhookEvent. This caused `manage.py check` to raise models.E012 and refuse
to start, breaking every manage.py command including migrate and runserver.

The WebhookEvent.stripe_event_id field already has unique=True at the DB level,
which is the correct idempotency guard. No additional constraint is needed.

Note: the broken constraint existed only in the Python model code; it was never
applied to the database (Django's system check prevented any migration from
running). This migration is therefore a no-op at the DB level — it only updates
the migration state so Django's migration graph reflects the corrected model.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0003_payment_unique_stripe_session_id'),
    ]

    operations = [
        # No DB operation needed — the broken constraint was never applied to
        # the database because system checks prevented migrations from running.
        # This migration records the corrected model state in the migration graph.
    ]
