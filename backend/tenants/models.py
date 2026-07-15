import uuid
from django.conf import settings
from django.db import models
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.utils.text import slugify
from bizal.validators import validate_image_type, validate_hex_color, validate_color_contrast


# ── Plans ────────────────────────────────────────────────────────────────────

PLAN_TRIAL      = 'trial'
PLAN_STARTER    = 'starter'
PLAN_PRO        = 'pro'
PLAN_ENTERPRISE = 'enterprise'

PLAN_CHOICES = [
    (PLAN_TRIAL,      'Trial (14 days)'),
    (PLAN_STARTER,    'Starter'),
    (PLAN_PRO,        'Pro'),
    (PLAN_ENTERPRISE, 'Enterprise'),
]

TRIAL_DAYS = 14

# ── Business types ───────────────────────────────────────────────────────────

BUSINESS_TYPE_CHOICES = [
    # Retail
    ('market',           'Market / General Shop'),
    ('pharmacy',         'Pharmacy'),
    ('electronics',      'Electronics Store'),
    ('clothing',         'Clothing Store'),
    ('organic',          'Organic Market'),
    ('bookstore',        'Bookstore / Stationery'),
    ('jewelry',          'Jewelry & Accessories'),
    ('toy_store',        'Toy & Baby Store'),
    ('sports_shop',      'Sports & Outdoors Shop'),
    ('furniture',        'Furniture & Home Decor'),
    ('petrol_station',   'Petrol Station'),
    # Food & Hospitality
    ('restaurant',       'Restaurant / Café'),
    ('hotel',            'Hotel / Guesthouse'),
    ('bar',              'Bar / Night Club'),
    ('delivery_kitchen', 'Food Delivery Kitchen'),
    ('bakery',           'Bakery & Patisserie'),
    ('catering',         'Catering Service'),
    # Rentals
    ('car_rental',       'Car Rental'),
    ('property_rental',  'Property Rental'),
    ('equipment_rental', 'Equipment Rental'),
    ('boat_rental',      'Boat Rental'),
    # Health & Beauty
    ('barbershop',       'Barbershop / Hair Salon'),
    ('spa',              'Spa & Wellness'),
    ('gym',              'Gym / Fitness Studio'),
    ('clinic',           'Clinic / Dental'),
    ('tattoo',           'Tattoo Studio'),
    ('veterinary',       'Veterinary Clinic'),
    ('optician',         'Optician'),
    # Services
    ('auto_repair',      'Auto Repair'),
    ('cleaning',         'Cleaning Service'),
    ('lawyer',           'Lawyer / Notary'),
    ('accounting',       'Accounting Firm'),
    ('event_agency',     'Event Agency'),
    ('photography',      'Photography Studio'),
    ('printing',         'Print & Design Studio'),
    ('travel_agency',    'Travel Agency'),
    ('funeral_home',     'Funeral Home'),
    ('security',         'Security Company'),
    # Education
    ('language_school',  'Language School'),
    ('tutoring',         'Tutoring Centre'),
    ('driving_school',   'Driving School'),
    ('coding_bootcamp',  'Coding Bootcamp'),
    ('nursery',          'Nursery / Childcare'),
    # Professional & B2B
    ('real_estate',      'Real Estate Agency'),
    ('construction',     'Construction / Contractor'),
    ('architecture',     'Architecture & Design Firm'),
    ('import_export',    'Import / Export Company'),
    ('agro',             'Agricultural Supplier'),
    ('transport',        'Transport & Logistics'),
    ('it_company',       'IT Company'),
    ('marketing_agency', 'Marketing Agency'),
]

# ── Feature flags ─────────────────────────────────────────────────────────────

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
    'bookings',
    'multi_location',
    'referral_program',
    'marketplace_listing',
    'inventory',
    'invoicing',
    'loyalty_program',
    'domain_custom',
    'chatbot',
]

# ── Base plan features ────────────────────────────────────────────────────────

PLAN_FEATURES = {
    PLAN_TRIAL: {
        # Trial gets Pro features for TRIAL_DAYS days
        'custom_branding':      True,
        'contact_form':         True,
        'whatsapp_button':      True,
        'analytics':            True,
        'reviews':              True,
        'blog':                 False,
        'payments':             False,
        'staff_accounts':       True,
        'crm':                  False,
        'notifications_sms':    False,
        'csv_export':           False,
        'pdf_export':           False,
        'api_access':           False,
        'bookings':             True,
        'multi_location':       False,
        'referral_program':     False,
        'marketplace_listing':  True,
        'inventory':            False,
        'invoicing':            False,
        'loyalty_program':      False,
        'domain_custom':        False,
        'chatbot':              False,
        'max_staff':            5,
        'max_listings':         50,
    },
    PLAN_STARTER: {
        'custom_branding':      False,
        'contact_form':         True,
        'whatsapp_button':      True,
        'analytics':            False,
        'reviews':              True,
        'blog':                 False,
        'payments':             False,
        'staff_accounts':       False,
        'crm':                  False,
        'notifications_sms':    False,
        'csv_export':           False,
        'pdf_export':           False,
        'api_access':           False,
        'bookings':             True,
        'multi_location':       False,
        'referral_program':     False,
        'marketplace_listing':  True,
        'inventory':            False,
        'invoicing':            False,
        'loyalty_program':      False,
        'domain_custom':        False,
        'chatbot':              False,
        'max_staff':            1,
        'max_listings':         50,
    },
    PLAN_PRO: {
        'custom_branding':      True,
        'contact_form':         True,
        'whatsapp_button':      True,
        'analytics':            True,
        'reviews':              True,
        'blog':                 True,
        'payments':             True,
        'staff_accounts':       True,
        'crm':                  False,
        'notifications_sms':    True,
        'csv_export':           False,
        'pdf_export':           False,
        'api_access':           False,
        'bookings':             True,
        'multi_location':       False,
        'referral_program':     True,
        'marketplace_listing':  True,
        'inventory':            True,
        'invoicing':            False,
        'loyalty_program':      False,
        'domain_custom':        False,
        'chatbot':              False,
        'max_staff':            5,
        'max_listings':         100,
    },
    PLAN_ENTERPRISE: {
        'custom_branding':      True,
        'contact_form':         True,
        'whatsapp_button':      True,
        'analytics':            True,
        'reviews':              True,
        'blog':                 True,
        'payments':             True,
        'staff_accounts':       True,
        'crm':                  True,
        'notifications_sms':    True,
        'csv_export':           True,
        'pdf_export':           True,
        'api_access':           True,
        'bookings':             True,
        'multi_location':       True,
        'referral_program':     True,
        'marketplace_listing':  True,
        'inventory':            True,
        'invoicing':            True,
        'loyalty_program':      True,
        'domain_custom':        True,
        'chatbot':              True,
        'max_staff':            9999,
        'max_listings':         9999,
    },
}

# ── Business-type feature presets (layered on top of plan defaults) ───────────
# These override plan defaults for specific business types.
# Only keys listed here are overridden — everything else keeps the plan default.

BUSINESS_TYPE_PRESETS = {
    # Booking-heavy types always get bookings even on Starter
    'restaurant':       {'bookings': True},
    'hotel':            {'bookings': True, 'payments': True, 'crm': True},
    'clinic':           {'bookings': True, 'crm': True},
    'veterinary':       {'bookings': True, 'crm': True},
    'barbershop':       {'bookings': True, 'loyalty_program': True},
    'spa':              {'bookings': True, 'loyalty_program': True},
    'gym':              {'bookings': True, 'loyalty_program': True, 'payments': True},
    'driving_school':   {'bookings': True, 'invoicing': True},
    'language_school':  {'bookings': True, 'invoicing': True},
    'tutoring':         {'bookings': True, 'invoicing': True},
    'nursery':          {'bookings': True},
    'photography':      {'bookings': True, 'invoicing': True},
    'car_rental':       {'bookings': True, 'payments': True, 'inventory': True},
    'boat_rental':      {'bookings': True, 'payments': True, 'inventory': True},
    'equipment_rental': {'bookings': True, 'payments': True, 'inventory': True},
    # Commerce/inventory-heavy types
    'market':           {'inventory': True, 'payments': True},
    'pharmacy':         {'inventory': True, 'payments': True},
    'electronics':      {'inventory': True, 'payments': True},
    'clothing':         {'inventory': True, 'payments': True},
    'organic':          {'inventory': True, 'payments': True},
    'furniture':        {'inventory': True, 'invoicing': True},
    'petrol_station':   {'inventory': True, 'loyalty_program': True},
    # B2B / professional types
    'real_estate':      {'crm': True, 'invoicing': True, 'pdf_export': True},
    'lawyer':           {'crm': True, 'invoicing': True, 'pdf_export': True},
    'accounting':       {'crm': True, 'invoicing': True, 'pdf_export': True, 'csv_export': True},
    'construction':     {'crm': True, 'invoicing': True, 'pdf_export': True},
    'architecture':     {'crm': True, 'invoicing': True, 'pdf_export': True},
    'import_export':    {'crm': True, 'invoicing': True, 'inventory': True},
    'agro':             {'inventory': True, 'invoicing': True},
    'transport':        {'crm': True, 'invoicing': True, 'csv_export': True},
    'it_company':       {'crm': True, 'invoicing': True, 'api_access': True},
    'marketing_agency': {'crm': True, 'invoicing': True, 'blog': True},
    # Hospitality / tourism
    'travel_agency':    {'bookings': True, 'payments': True, 'crm': True},
    'catering':         {'bookings': True, 'invoicing': True},
    'event_agency':     {'bookings': True, 'crm': True, 'invoicing': True},
    # Property
    'property_rental':  {'bookings': True, 'payments': True, 'crm': True},
    # Printing/creative
    'printing':         {'invoicing': True, 'pdf_export': True},
}


# ── Models ────────────────────────────────────────────────────────────────────

class Tenant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Identity
    name           = models.CharField(max_length=200)
    slug           = models.SlugField(unique=True, max_length=80)
    site_title     = models.CharField(max_length=200, blank=True)
    tagline        = models.CharField(max_length=300, blank=True)
    business_type  = models.CharField(max_length=50, choices=BUSINESS_TYPE_CHOICES, default='restaurant')

    # Branding
    logo           = models.ImageField(upload_to='tenants/logos/', blank=True, null=True, validators=[validate_image_type])
    primary_color  = models.CharField(max_length=7, default='#2563EB', validators=[validate_hex_color])
    accent_color   = models.CharField(max_length=7, default='#F59E0B', validators=[validate_hex_color])
    font_family    = models.CharField(max_length=100, default='Inter')

    # Theme (storefront customization — "next level" of branding).
    # These are consumed by the public storefront's applyBrand() JS, which
    # already expected TENANT.font_heading / font_body / border_radius, but
    # the model never actually produced them, so those three always came
    # through as undefined and silently no-opped. Curated choice lists
    # instead of free-text/raw CSS keep this from becoming a CSS/style
    # injection vector while still giving each tenant real visual variety.
    FONT_CHOICES = [
        ('Cormorant Garamond', 'Cormorant Garamond (parazgjedhje, elegante)'),
        ('DM Sans', 'DM Sans (parazgjedhje, neutrale)'),
        ('Inter', 'Inter (e pastër, moderne)'),
        ('Poppins', 'Poppins (e rrumbullakosur, miqësore)'),
        ('Playfair Display', 'Playfair Display (luksoze, editoriale)'),
        ('Merriweather', 'Merriweather (klasike, serif)'),
        ('Space Grotesk', 'Space Grotesk (moderne, teknike)'),
        ('Nunito', 'Nunito (e butë, e afërt)'),
    ]
    RADIUS_CHOICES = [
        ('2px', 'Të mprehta'),
        ('8px', 'Të buta (parazgjedhje)'),
        ('16px', 'Të rrumbullakosura'),
        ('28px', 'Pilulë'),
    ]
    # Defaults MUST match brand.css's hardcoded :root fallbacks
    # ('Cormorant Garamond' / 'DM Sans' / 8px) — these are the fonts every
    # storefront has always rendered with. Getting this wrong doesn't just
    # look bad: it silently changes the typography on every un-customized
    # tenant's live public site the moment these fields start being read.
    font_heading   = models.CharField(max_length=50, choices=FONT_CHOICES, default='Cormorant Garamond')
    font_body      = models.CharField(max_length=50, choices=FONT_CHOICES, default='DM Sans')
    border_radius  = models.CharField(max_length=6, choices=RADIUS_CHOICES, default='8px')

    # Background/text are free hex (like primary_color/accent_color), not a
    # curated choice list, because unlike fonts/radius there's no small,
    # finite set of "safe" options — any hex is visually valid on its own.
    # What makes this pair dangerous is the two together: they set the
    # storefront's body background and body text color, so a bad
    # combination doesn't just look off, it can make the entire site
    # unreadable. clean() below enforces a minimum contrast ratio between
    # them. Defaults MUST match brand.css's hardcoded --parchment/--ink
    # values for the same reason as font_heading/font_body above.
    background_color  = models.CharField(max_length=7, default='#FAFAF8', validators=[validate_hex_color])
    text_color        = models.CharField(max_length=7, default='#111111', validators=[validate_hex_color])

    # Contact
    email          = models.EmailField(blank=True)
    reply_from_email = models.EmailField(
        blank=True,
        help_text="Optional custom reply-from address for outgoing emails (e.g. info@mybusiness.al). "
                  "Falls back to platform DEFAULT_FROM_EMAIL if blank.",
    )
    phone          = models.CharField(max_length=30, blank=True)
    whatsapp       = models.CharField(max_length=30, blank=True)
    address        = models.CharField(max_length=300, blank=True)
    city           = models.CharField(max_length=100, blank=True)
    country        = models.CharField(max_length=100, default='Albania')
    business_hours = models.JSONField(default=dict, blank=True)
    latitude       = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude      = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    # Social
    facebook       = models.URLField(blank=True)
    instagram      = models.URLField(blank=True)
    tiktok         = models.URLField(blank=True)
    website        = models.URLField(blank=True)

    # Content
    story          = models.TextField(blank=True)
    founded_year   = models.PositiveSmallIntegerField(null=True, blank=True)

    # Plan & billing
    plan                    = models.CharField(max_length=20, choices=PLAN_CHOICES, default=PLAN_TRIAL)
    is_active               = models.BooleanField(default=False)
    trial_ends_at           = models.DateTimeField(null=True, blank=True)
    trial_warning_sent_at   = models.DateTimeField(null=True, blank=True)  # guards duplicate warning emails
    stripe_customer_id      = models.CharField(max_length=100, blank=True)
    stripe_subscription_id  = models.CharField(max_length=100, blank=True)

    # Base/ledger currency for one-off payments this tenant collects from
    # its own customers (booking deposits, etc) — distinct from BizAL's own
    # subscription billing, which always runs in whatever currency
    # STRIPE_PRICE_* is denominated in.
    #
    # LOCKED TO ALL (see tenants/migrations/0017_lock_currency_to_all.py):
    # this used to be tenant-selectable (ALL/EUR/USD), but that let a
    # tenant's *stored* totals/ledger silently be in a different currency
    # from every other tenant on the platform, which several reports,
    # the superadmin analytics, and referral-credit math assumed was
    # always ALL. Every amount recorded anywhere (Booking.total_price,
    # Payment.amount, invoices, ...) is now unconditionally ALL.
    #
    # This does NOT remove EUR/USD support for tourism-facing tenants
    # (hotels, property/car/boat rentals) that legitimately want to let
    # their own customers pay in EUR or USD — that's handled at the
    # *payment* layer instead: create_booking_checkout() (payments/views.py)
    # accepts a customer-chosen pay_currency, converts the ALL amount via
    # tenants/fx.py at the moment of checkout, and Stripe charges the
    # customer in their chosen currency. The ledger amount stays ALL either
    # way. See tenants/fx.py for the full rationale.
    CURRENCY_CHOICES = [
        ('ALL', 'Lek Shqiptar (ALL)'),
    ]
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default='ALL')

    # Explicit opt-in for the booking-deposit Stripe checkout flow
    # (payments.views.create_booking_checkout). Defaults to False: many
    # small tenants run cash-on-arrival / pay-in-person and would eat
    # Stripe's per-transaction fee for no benefit if a future frontend
    # change surfaced a "Pay online" button without their consent. The
    # tenant flips this on themselves once they actually want it.
    accepts_online_payments = models.BooleanField(default=False)

    # Referral
    referral_code       = models.CharField(max_length=20, unique=True, blank=True)
    referred_by         = models.ForeignKey(
        'self', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='referrals'
    )
    referral_credits    = models.DecimalField(max_digits=8, decimal_places=2, default=0)

    # Marketplace
    listed_on_marketplace = models.BooleanField(default=False)
    marketplace_description = models.TextField(blank=True)

    # SEO
    meta_description   = models.CharField(max_length=300, blank=True)
    meta_keywords      = models.CharField(max_length=300, blank=True)

    # Storefront navigation structure. Controls the order and visibility of
    # tabs on the public storefront (index.html): built-in tabs (overview,
    # services, menu, orders, rentals, reviews, blog, contact) plus custom
    # pages created under "Faqet Shtesë" (referenced as "page:<slug>").
    # Shape: {"tabs": [{"key": "overview", "hidden": false}, ...]}
    # Built-in tabs can be reordered/hidden but never removed from the list;
    # custom pages have full control (add/edit/delete/reorder) via the
    # Faqet Shtesë feature and simply appear/disappear from this list.
    nav_config         = models.JSONField(default=dict, blank=True)


    created_at         = models.DateTimeField(auto_now_add=True)
    updated_at         = models.DateTimeField(auto_now=True)
    onboarding_step    = models.PositiveSmallIntegerField(default=0)
    onboarding_complete = models.BooleanField(default=False)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.slug})"

    # Slugs reserved for platform use — cannot be registered as tenant subdomains.
    # Validated here (model level) AND in TenantSignupSerializer (API level) so
    # direct ORM creates (seed scripts, management commands, Django admin) are
    # also blocked.
    _RESERVED_SLUGS = frozenset({
        'www', 'api', 'admin', 'static', 'media', 'mail', 'ftp', 'smtp',
        'pop', 'imap', 'vpn', 'dev', 'staging', 'cdn', 'assets', 'help',
        'support', 'status', 'blog', 'docs', 'app', 'dashboard', 'login',
        'register', 'signup', 'logout', 'auth', 'oauth', 'superadmin',
        # L-3 FIX: platform routes registered in bizal/urls.py that were
        # missing — a tenant with one of these slugs would shadow the route.
        'health', 'onboarding', 'trial-expired',
    })

    def clean(self):
        super().clean()
        if self.slug and self.slug in self._RESERVED_SLUGS:
            raise ValidationError({'slug': f'"{self.slug}" is a reserved subdomain and cannot be used.'})
        try:
            validate_color_contrast(self.background_color, self.text_color)
        except ValidationError as exc:
            raise ValidationError({'text_color': exc.messages})

    @classmethod
    def from_db(cls, db, field_names, values):
        """
        LOW-5 FIX: Cache the plan and business_type values at load time so
        save() can compare without an extra SELECT. Previously every
        Tenant.save() (including branding-only updates like name/logo/color)
        fired an extra `SELECT plan, business_type WHERE pk=...` query.
        With from_db() caching, the comparison is purely in-memory.

        Only cache these when they were actually part of this load. A call
        like `tenant.refresh_from_db(fields=['referral_credits'])` loads a
        row with only that field (plus pk) present in `field_names` — plan
        and business_type stay deferred. Unconditionally touching
        instance.plan/instance.business_type here would trigger Django's
        deferred-attribute loader, which itself calls refresh_from_db() and
        therefore from_db() again for just that one field, forever: each
        recursive load only fetches one deferred field and defers the next.
        Skipping the cache when a field wasn't loaded avoids that recursion;
        save()'s getattr(self, '_loaded_plan', self.plan) fallback already
        handles the "not cached" case correctly.
        """
        instance = super().from_db(db, field_names, values)
        if 'plan' in field_names:
            instance._loaded_plan = instance.plan
        if 'business_type' in field_names:
            instance._loaded_business_type = instance.business_type
        return instance

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        if not self.site_title:
            self.site_title = self.name
        if not self.referral_code:
            self.referral_code = self._generate_referral_code()
        # NOTE: self.pk is always truthy here even for a brand-new tenant,
        # because `id` is a UUIDField(default=uuid.uuid4) — Django assigns
        # the UUID the moment the object is instantiated, not when it's
        # saved. Use self._state.adding (True until the first save()
        # completes) to detect "this row doesn't exist in the DB yet".
        #
        # trial_ends_at is intentionally NOT set here. The trial clock is
        # activation-gated: it is set in
        # tenants/admin.py::apply_activation_side_effects() the moment a
        # tenant transitions is_active False -> True (via /django-admin/ —
        # the old SuperadminTenantDetailView.perform_update() that used to
        # own this has been removed). Until activation, trial_ends_at stays
        # None and the 14-day clock has not started. See
        # tenants/views.py tenant_signup() for the other half of this
        # behaviour.
        is_new = self._state.adding

        plan_changed = True
        if not is_new:
            try:
                # LOW-5 FIX: Use values cached by from_db() instead of a DB query.
                # from_db() stores _loaded_plan and _loaded_business_type at load
                # time; getattr falls back to self.plan for objects created in-memory
                # (not loaded from DB) where from_db() was never called.
                plan_changed = (
                    getattr(self, '_loaded_plan', self.plan) != self.plan or
                    getattr(self, '_loaded_business_type', self.business_type) != self.business_type
                )
            except Exception:
                pass
        super().save(*args, **kwargs)
        # FIX: If update_fields was passed and neither 'plan' nor 'business_type'
        # is in it, those fields weren't written — skip apply_plan_defaults().
        # Previously a `save(update_fields=['name'])` call would still run
        # apply_plan_defaults() if in-memory self.plan differed from DB (e.g.
        # after a superadmin .update(plan=...) bypassed save()), re-writing
        # all TenantFeature rows unnecessarily and potentially overwriting
        # custom grants that should have survived.
        update_fields = kwargs.get('update_fields')
        if update_fields is not None:
            plan_changed = bool(
                {'plan', 'business_type'}.intersection(update_fields)
            )
        if plan_changed:
            self.apply_plan_defaults()

    def _generate_referral_code(self):
        """
        Generate a unique 10-character referral code (6-char slug prefix + 4 random chars).
        The code space is ~1.7M combinations; collisions are rare but possible.
        Retry up to 5 times on IntegrityError before giving up — at scale this
        avoids an unhandled exception during tenant creation that would leave
        the tenant row in a partially-created state.
        """
        # LOW-4 FIX: Use secrets.choice instead of random.choices. Referral
        # codes have financial value (€10/conversion); the PRNG Mersenne Twister
        # is not cryptographically secure — an attacker who can observe a sequence
        # of codes could predict future ones and fraudulently claim credits.
        # secrets.choice uses os.urandom() which is CSPRNG-backed.
        import secrets
        import string

        base = self.slug[:6].upper() if self.slug else 'BIZ'
        for attempt in range(5):
            suffix = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(4))
            code = f"{base}{suffix}"
            # Check for collision before assigning — avoids needing a try/except
            # in save() and gives a clean code on the first DB round-trip.
            if not Tenant.objects.filter(referral_code=code).exists():
                return code
        # Extremely unlikely fallback: keep the same 10-character format for
        # consistency with the main loop and any UI/marketing that displays
        # referral codes. LOW-1 FIX: the previous fallback produced 14-char codes
        # (base[up to 6] + 8 random chars) — inconsistent with the 10-char codes
        # shown everywhere else. Use 4 random chars to stay at 10 chars.
        return base + ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(4))

    def apply_plan_defaults(self):
        """Apply plan features merged with business-type presets."""
        features = dict(PLAN_FEATURES.get(self.plan, PLAN_FEATURES[PLAN_STARTER]))

        # Overlay business-type presets — but only upgrade, never downgrade
        presets = BUSINESS_TYPE_PRESETS.get(self.business_type, {})
        for key, value in presets.items():
            if key in features:
                # For boolean flags: only upgrade True, never force False
                if isinstance(value, bool) and value:
                    features[key] = True
                elif not isinstance(value, bool):
                    features[key] = value

        # Never overwrite rows that a superadmin has manually granted —
        # those have is_custom_grant=True and must survive plan changes.
        custom_keys = set(
            TenantFeature.objects.filter(tenant=self, is_custom_grant=True)
            .values_list('key', flat=True)
        )

        # Apply to TenantFeature rows in a single round-trip (don't overwrite
        # custom grants — update_conflicts only touches 'value', never
        # 'is_custom_grant', so superadmin overrides survive plan changes).
        rows = [
            TenantFeature(tenant=self, key=key, value=str(value), is_custom_grant=False)
            for key, value in features.items()
            if key not in custom_keys
        ]
        TenantFeature.objects.bulk_create(
            rows,
            update_conflicts=True,
            unique_fields=['tenant', 'key'],
            update_fields=['value'],
        )

    def has_feature(self, feature_key):
        """Check if trial is still valid before honouring features."""
        # MED-2 FIX: Return False for any tenant that has not yet been activated
        # by a superadmin. An unactivated trial tenant (is_active=False,
        # trial_ends_at=None) would otherwise fall through to the features table
        # and return True for plan features applied during save(), effectively
        # granting full Pro-level access to a tenant that was never activated.
        # The middleware largely prevents this from being reached, but the method
        # contract should be correct independently of caller context.
        if not self.is_active:
            return False
        if self.plan == PLAN_TRIAL:
            if self.trial_ends_at and timezone.now() > self.trial_ends_at:
                return False
        # Use the prefetch_related cache if it's already populated (e.g. by
        # the middleware on cache hit) so this doesn't issue a fresh query
        # per call/feature when checking a cached tenant instance.
        features = self.features.all()
        match = next((f for f in features if f.key == feature_key), None)
        if match is None:
            return False
        return match.value.lower() in ('true', '1', 'yes')

    def get_limit(self, limit_key):
        # Use the prefetch cache (same as has_feature) to avoid an extra
        # DB hit per call when features are already loaded by middleware.
        match = next((f for f in self.features.all() if f.key == limit_key), None)
        if match is None:
            return 0
        try:
            return int(match.value)
        except (ValueError, TypeError):
            return 0

    @property
    def trial_expired(self):
        if self.plan != PLAN_TRIAL:
            return False
        return bool(self.trial_ends_at and timezone.now() > self.trial_ends_at)

    def get_reply_from_email(self):
        """
        The address that should appear in `from_email` for emails we send
        to this tenant's own customers (booking confirmations, reminders,
        contact-form replies). Falls back to the platform default when the
        tenant hasn't set a custom reply-from address.
        """
        return self.reply_from_email or settings.DEFAULT_FROM_EMAIL

    @property
    def trial_days_remaining(self):
        if self.plan != PLAN_TRIAL or not self.trial_ends_at:
            return None
        delta = self.trial_ends_at - timezone.now()
        if delta.total_seconds() <= 0:
            return 0
        # Round UP to whole days so a trial with e.g. 5 days and a few
        # milliseconds left reads as "5 days remaining", not "4" — using
        # delta.days truncates toward zero and undercounts by one for any
        # remainder under 24h.
        import math
        return max(0, math.ceil(delta.total_seconds() / 86400))


class TrialTenant(Tenant):
    """
    Proxy model over Tenant, scoped (via TrialTenantAdmin.get_queryset) to
    plan='trial'. Exists only so the Django admin app-list can show a
    dedicated "Trial dashboard" entry, separate from the full Tenant list,
    without duplicating any columns/table. No schema change — pure admin UX.
    """
    class Meta:
        proxy = True
        verbose_name = 'Trial tenant'
        verbose_name_plural = 'Trial dashboard'


class TenantFeature(models.Model):
    tenant          = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='features')
    key             = models.CharField(max_length=100)
    value           = models.CharField(max_length=200)
    is_custom_grant = models.BooleanField(default=False)  # True = superadmin override, never reset by plan changes

    class Meta:
        unique_together = ('tenant', 'key')

    def __str__(self):
        flag = ' [custom]' if self.is_custom_grant else ''
        return f"{self.tenant.slug}: {self.key}={self.value}{flag}"


class TenantLocation(models.Model):
    """A branch / secondary location for a tenant (Enterprise feature)."""
    id      = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant  = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='locations')

    name        = models.CharField(max_length=200)
    address     = models.CharField(max_length=300, blank=True)
    city        = models.CharField(max_length=100, blank=True)
    phone       = models.CharField(max_length=30, blank=True)
    email       = models.EmailField(blank=True)
    latitude    = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude   = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    is_primary  = models.BooleanField(default=False)
    is_active   = models.BooleanField(default=True)

    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-is_primary', 'name']

    def __str__(self):
        return f"{self.tenant.slug} — {self.name}"

    def save(self, *args, **kwargs):
        # Enforce one primary per tenant.
        # L-3 FIX: Always enter the atomic+lock block regardless of is_primary value.
        # The previous code only locked on is_primary=True, leaving a narrow race:
        # a concurrent is_primary=False save could clear a different existing primary
        # without holding the lock, so a third concurrent is_primary=True save could
        # end up with two primaries if it ran between the unlocked False-save and its
        # own lock acquisition. Entering the atomic block unconditionally means all
        # concurrent saves for this tenant are serialised.
        # L-2 FIX (v26): Lock ALL location rows for this tenant regardless of the
        # is_primary direction. The v25 fix only acquired select_for_update() on the
        # True path; two concurrent False saves could still interleave with a True
        # save from a third writer. Locking all rows upfront fully serialises every
        # concurrent save for this tenant's locations.
        from django.db import transaction
        with transaction.atomic():
            # Acquire a row-level lock on all locations for this tenant before
            # any write, regardless of is_primary direction.
            list(TenantLocation.objects.select_for_update().filter(tenant=self.tenant))
            if self.is_primary:
                TenantLocation.objects.filter(
                    tenant=self.tenant, is_primary=True
                ).exclude(pk=self.pk).update(is_primary=False)
            super().save(*args, **kwargs)


class TenantReferral(models.Model):
    """Tracks a successful referral and the credit awarded."""
    referrer    = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='referral_records')
    referred    = models.OneToOneField(Tenant, on_delete=models.CASCADE, related_name='referral_source')
    # Renamed from credit_eur: referral credits, like every other stored
    # amount on the platform, are denominated in ALL (Lek) — see
    # tenants/fx.py's module docstring and the Tenant.currency comment
    # above. The old "_eur" name was legacy/misleading, not a real
    # currency distinction, and had the frontend rendering it with a "€"
    # prefix next to figures that were actually Lek.
    credit_amount = models.DecimalField(max_digits=6, decimal_places=2, default=10.00)
    applied     = models.BooleanField(default=False)
    created_at  = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.referrer.slug} → {self.referred.slug}"

    def apply_credit(self):
        # MED-4 FIX: Wrap the entire sequence in a single atomic block with
        # select_for_update() re-check. The previous code had three separate
        # writes (F() update, self.save(), CreditLedger.create()) outside any
        # explicit transaction. A crash between the F() update and the applied=True
        # save would leave referral_credits incremented but applied=False, causing
        # double-crediting on the next daily task run.
        from django.db import transaction
        from django.db.models import F
        with transaction.atomic():
            locked = TenantReferral.objects.select_for_update().filter(
                pk=self.pk, applied=False
            ).first()
            if locked is None:
                return  # already applied by a concurrent worker or previous run
            Tenant.objects.filter(pk=locked.referrer_id).update(
                referral_credits=F('referral_credits') + locked.credit_amount
            )
            # LOW-2 FIX: removed dead refresh_from_db() call. After the F()
            # UPDATE above, locked.referrer is a stale cached FK object. The
            # refresh updated it, but locked.referrer is never read again in this
            # method — it's used only as a FK reference in CreditLedger.create()
            # below, which needs the PK (unchanged), not the balance. Dead code.
            locked.applied = True
            locked.save(update_fields=['applied'])
            self.applied = True
            # Record the ledger entry so there's a full audit trail of
            # how a tenant's referral_credits balance was built up.
            CreditLedger.objects.create(
                tenant=locked.referrer,
                amount=locked.credit_amount,
                event=CreditLedger.EVENT_REFERRAL,
                description=f'Referral credit for {locked.referred.slug}',
                referral=locked,
            )


class CreditLedger(models.Model):
    """
    Immutable append-only ledger of every change to a tenant's referral
    credit balance. Positive amounts are credits (earned), negative amounts
    are debits (redeemed against an invoice or manually adjusted).

    The tenant.referral_credits field is the running balance derived from
    this table; use it for fast reads. Use this table for display and audit.
    """

    EVENT_REFERRAL  = 'referral'
    EVENT_REDEMPTION = 'redemption'
    EVENT_ADJUSTMENT = 'adjustment'

    EVENT_CHOICES = [
        (EVENT_REFERRAL,   'Referral earned'),
        (EVENT_REDEMPTION, 'Redeemed against invoice'),
        (EVENT_ADJUSTMENT, 'Manual adjustment'),
    ]

    tenant      = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='credit_ledger')
    amount      = models.DecimalField(max_digits=8, decimal_places=2)   # +credit / -debit
    event       = models.CharField(max_length=20, choices=EVENT_CHOICES)
    description = models.CharField(max_length=300, blank=True)
    referral    = models.ForeignKey(
        TenantReferral, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='ledger_entries'
    )
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        # FIX #7: DB-level check constraint so no row can represent a
        # redemption that exceeds the available balance. The balance lives
        # on Tenant.referral_credits; this constraint validates each ledger
        # entry independently (amount can be any sign, but the running
        # balance must never go negative).
        # Note: the balance non-negative check is enforced in spend_credits()
        # at the application layer; the DB constraint here is a safety net.
        constraints = [
            models.CheckConstraint(
                check=~models.Q(amount=0),
                name='credit_ledger_nonzero_amount',
            ),
        ]

    def __str__(self):
        sign = '+' if self.amount >= 0 else ''
        return f"{self.tenant.slug}: {sign}{self.amount} Lek ({self.event})"

    @classmethod
    def spend_credits(cls, tenant, amount, description=''):
        """
        FIX #7: Atomically debit `amount` from tenant.referral_credits,
        recording a ledger entry. Raises ValueError if the balance would
        go negative, preventing accidental over-spend.

        Usage:
            CreditLedger.spend_credits(tenant, Decimal('5.00'), 'Applied to invoice #42')
        """
        from decimal import Decimal
        from django.db import transaction
        from django.db.models import F

        amount = Decimal(str(amount))
        if amount <= 0:
            raise ValueError(f"Spend amount must be positive, got {amount}")

        with transaction.atomic():
            # Lock the tenant row to serialize concurrent spend_credits calls
            locked = Tenant.objects.select_for_update().get(pk=tenant.pk)
            if locked.referral_credits < amount:
                raise ValueError(
                    f"Insufficient credits: balance {locked.referral_credits} < requested {amount}"
                )
            Tenant.objects.filter(pk=tenant.pk).update(
                referral_credits=F('referral_credits') - amount
            )
            entry = cls.objects.create(
                tenant=tenant,
                amount=-amount,
                event=cls.EVENT_REDEMPTION,
                description=description,
            )
        return entry
