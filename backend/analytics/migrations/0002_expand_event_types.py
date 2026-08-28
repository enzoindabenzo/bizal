from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ('analytics', '0001_initial'),
    ]
    operations = [
        migrations.AlterField(
            model_name='analyticsevent',
            name='event_type',
            field=models.CharField(
                max_length=50,
                choices=[
                    ('page_view',          'Page View'),
                    ('booking_created',    'Booking Created'),
                    ('appointment_booked', 'Appointment Booked'),
                    ('order_placed',       'Order Placed'),
                    ('contact_submitted',  'Contact Form Submitted'),
                    ('review_submitted',   'Review Submitted'),
                    ('service_viewed',     'Service Viewed'),
                    ('menu_viewed',        'Menu Viewed'),
                    ('product_viewed',     'Product Viewed'),
                    ('listing_viewed',     'Listing Viewed'),
                    ('package_viewed',     'Package Viewed'),
                    ('whatsapp_click',     'WhatsApp Button Clicked'),
                    ('phone_click',        'Phone Number Clicked'),
                    ('map_click',          'Map/Directions Clicked'),
                    ('instagram_click',    'Instagram Link Clicked'),
                    ('lead_created',       'CRM Lead Created'),
                    ('invoice_viewed',     'Invoice Viewed'),
                    ('location_switched',  'Branch Location Switched'),
                ],
            ),
        ),
    ]
