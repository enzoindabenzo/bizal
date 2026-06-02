import uuid
from django.db import models
from django.utils.text import slugify


PLAN_STARTER = 'starter'
PLAN_PRO = 'pro'
PLAN_ENTERPRISE = 'enterprise'

PLAN_CHOICES = [
    (PLAN_STARTER, 'Starter'),
    (PLAN_PRO, 'Pro'),
    (PLAN_ENTERPRISE, 'Enterprise'),
]

BUSINESS_TYPE_CHOICES = [
    # Retail
    ('market', 'Market / General Shop'),
    ('pharmacy', 'Pharmacy'),
    ('electronics', 'Electronics Store'),
    ('clothing', 'Clothing Store'),
    ('organic', 'Organic Market'),
    # Food & Hospitality
    ('restaurant', 'Restaurant / Café'),
    ('hotel', 'Hotel / Guesthouse'),
    ('bar', 'Bar / Night Club'),
    ('delivery_kitchen', 'Food Delivery Kitchen'),
    ('bakery', 'Bakery'),
    # Rentals
    ('car_rental', 'Car Rental'),
    ('property_rental', 'Property Rental'),
    ('equipment_rental', 'Equipment Rental'),
    ('boat_rental', 'Boat Rental'),
    # Health & Beauty
    ('barbershop', 'Barbershop / Hair Salon'),
    ('spa', 'Spa & Wellness'),
    ('gym', 'Gym / Fitness Studio'),
    ('clinic', 'Clinic / Dental'),
    ('tattoo', 'Tattoo Studio'),
    # Services
    ('auto_repair', 'Auto Repair'),
    ('cleaning', 'Cleaning Service'),
    ('lawyer', 'Lawyer / Notary'),
    ('accounting', 'Accounting Firm'),
    ('event_agency', 'Event Agency'),
    # Education
    ('language_school', 'Language School'),
    ('tutoring', 'Tutoring'),
    ('driving_school', 'Driving School'),
    ('coding_bootcamp', 'Coding Bootcamp'),
]

FEATURE_FLAGS = [
    'custom_branding',
    'contact_form',
    'whatsapp_button',
    'analytics',
    'reviews',
    'blog',
    'payments',
    'staff_accounts',
    'crm',
    'notifications_sms',
    'csv_export',
    'pdf_export',
    'api_access',
]

PLAN_FEATURES = {
    PLAN_STARTER: {
        'custom_branding': False,
        'contact_form': False,
        'whatsapp_button': False,
        'analytics': False,
        'reviews': False,
        'blog': False,
        'payments': False,
        'staff_accounts': False,
        'crm': False,
        'notifications_sms': False,
        'csv_export': False,
        'pdf_export': False,
        'api_access': False,
        'max_staff': 1,
        'max_listings': 10,
    },
    PLAN_PRO: {
        'custom_branding': True,
        'contact_form': True,
        'whatsapp_button': True,
        'analytics': True,
        'reviews': True,
        'blog': False,
        'payments': False,
        'staff_accounts': True,
        'crm': False,
        'notifications_sms': False,
        'csv_export': False,
        'pdf_export': False,
        'api_access': False,
        'max_staff': 5,
        'max_listings': 100,
    },
    PLAN_ENTERPRISE: {
        'custom_branding': True,
        'contact_form': True,
        'whatsapp_button': True,
        'analytics': True,
        'reviews': True,
        'blog': True,
        'payments': True,
        'staff_accounts': True,
        'crm': True,
        'notifications_sms': True,
        'csv_export': True,
        'pdf_export': True,
        'api_access': True,
        'max_staff': 9999,
        'max_listings': 9999,
    },
}


class Tenant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Identity
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True, max_length=80)
    site_title = models.CharField(max_length=200, blank=True)
    tagline = models.CharField(max_length=300, blank=True)
    business_type = models.CharField(max_length=50, choices=BUSINESS_TYPE_CHOICES, default='restaurant')

    # Branding
    logo = models.ImageField(upload_to='tenants/logos/', blank=True, null=True)
    primary_color = models.CharField(max_length=7, default='#2563EB')
    accent_color = models.CharField(max_length=7, default='#F59E0B')
    font_family = models.CharField(max_length=100, default='Inter')

    # Contact
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    whatsapp = models.CharField(max_length=30, blank=True)
    address = models.CharField(max_length=300, blank=True)
    city = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, default='Albania')
    business_hours = models.JSONField(default=dict, blank=True)

    # Social
    facebook = models.URLField(blank=True)
    instagram = models.URLField(blank=True)
    tiktok = models.URLField(blank=True)
    website = models.URLField(blank=True)

    # Content
    story = models.TextField(blank=True)
    founded_year = models.PositiveSmallIntegerField(null=True, blank=True)

    # Plan & billing
    plan = models.CharField(max_length=20, choices=PLAN_CHOICES, default=PLAN_STARTER)
    is_active = models.BooleanField(default=False)
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    stripe_customer_id = models.CharField(max_length=100, blank=True)
    stripe_subscription_id = models.CharField(max_length=100, blank=True)

    # SEO
    meta_description = models.CharField(max_length=300, blank=True)
    meta_keywords = models.CharField(max_length=300, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.slug})"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        if not self.site_title:
            self.site_title = self.name
        super().save(*args, **kwargs)
        self.apply_plan_defaults()

    def apply_plan_defaults(self):
        features = PLAN_FEATURES.get(self.plan, PLAN_FEATURES[PLAN_STARTER])
        for key, value in features.items():
            TenantFeature.objects.update_or_create(
                tenant=self, key=key,
                defaults={'value': str(value)}
            )

    def has_feature(self, feature_key):
        try:
            f = self.features.get(key=feature_key)
            return f.value.lower() in ('true', '1', 'yes')
        except TenantFeature.DoesNotExist:
            return False

    def get_limit(self, limit_key):
        try:
            f = self.features.get(key=limit_key)
            return int(f.value)
        except (TenantFeature.DoesNotExist, ValueError):
            return 0


class TenantFeature(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='features')
    key = models.CharField(max_length=100)
    value = models.CharField(max_length=200)

    class Meta:
        unique_together = ('tenant', 'key')

    def __str__(self):
        return f"{self.tenant.slug}: {self.key}={self.value}"
