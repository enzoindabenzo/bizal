# Hand-written merge migration that unifies all three competing 0002_* migrations.
# Previously only two of the three were listed as dependencies, meaning a clean
# database that applied all three 0002s independently would hit a migration
# graph conflict on `migrate`. Adding the third dependency here makes the graph
# unambiguous for both fresh installs and existing databases.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('analytics', '0002_alter_analyticsevent_tenant'),
        ('analytics', '0002_analyticsevent_indexes'),
        ('analytics', '0002_expand_event_types'),
    ]

    operations = [
    ]
