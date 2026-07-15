from django.db import models
from bizal.base_models import TenantScopedUUIDModel

EVENT_TYPES = [
    ('page_view',           'Page View'),
    ('booking_created',     'Booking Created'),
    ('appointment_booked',  'Appointment Booked'),
    ('order_placed',        'Order Placed'),
    ('contact_submitted',   'Contact Form Submitted'),
    ('review_submitted',    'Review Submitted'),
    ('service_viewed',      'Service Viewed'),
    ('menu_viewed',         'Menu Viewed'),
    ('product_viewed',      'Product Viewed'),
    ('listing_viewed',      'Listing Viewed'),       # real estate
    ('package_viewed',      'Package Viewed'),       # travel agency
    ('whatsapp_click',      'WhatsApp Button Clicked'),
    ('phone_click',         'Phone Number Clicked'),
    ('map_click',           'Map/Directions Clicked'),
    ('instagram_click',     'Instagram Link Clicked'),
    ('lead_created',        'CRM Lead Created'),
    ('invoice_viewed',      'Invoice Viewed'),
    ('location_switched',   'Branch Location Switched'),
]


class AnalyticsEvent(TenantScopedUUIDModel):
    """
    Lightweight event log for tenant analytics.
    Recorded by the frontend or by other apps via analytics.utils.track().
    """
    event_type = models.CharField(max_length=50, choices=EVENT_TYPES)
    page = models.CharField(max_length=300, blank=True)
    referrer = models.CharField(max_length=500, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)
    ip_hash = models.CharField(max_length=64, blank=True)   # hashed for privacy
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tenant', 'event_type']),
            models.Index(fields=['tenant', '-created_at']),
        ]

    def __str__(self):
        return f"{self.tenant.slug} | {self.event_type} @ {self.created_at:%Y-%m-%d %H:%M}"
