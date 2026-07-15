# Generated for BizAL v14 — adds 'chatbot' as a lead source

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('crm', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='lead',
            name='source',
            field=models.CharField(
                choices=[
                    ('website', 'Website'),
                    ('referral', 'Referral'),
                    ('social', 'Social Media'),
                    ('walk_in', 'Walk-in'),
                    ('chatbot', 'Chatbot'),
                    ('other', 'Other'),
                ],
                default='website',
                max_length=30,
            ),
        ),
    ]
