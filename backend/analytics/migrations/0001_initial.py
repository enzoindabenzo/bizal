from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('tenants', '0002_tenant_onboarding_complete_tenant_onboarding_step'),
    ]

    operations = [
        migrations.CreateModel(
            name='AnalyticsEvent',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('event_type', models.CharField(choices=[('page_view','Page View'),('booking_created','Booking Created'),('contact_submitted','Contact Form Submitted'),('review_submitted','Review Submitted'),('service_viewed','Service Viewed'),('menu_viewed','Menu Viewed'),('whatsapp_click','WhatsApp Button Clicked')], max_length=50)),
                ('page', models.CharField(blank=True, max_length=300)),
                ('referrer', models.CharField(blank=True, max_length=500)),
                ('user_agent', models.CharField(blank=True, max_length=500)),
                ('ip_hash', models.CharField(blank=True, max_length=64)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='analytics_events', to='tenants.tenant')),
            ],
            options={'ordering': ['-created_at']},
        ),
    ]
