from rest_framework import serializers
from bizal.validators import validate_color_contrast
from django.core.exceptions import ValidationError as DjangoValidationError
from .models import (
    Tenant, TenantFeature, TenantLocation, TenantReferral, CreditLedger,
    BUSINESS_TYPE_CHOICES, PLAN_CHOICES, PLAN_TRIAL,
)

# Built-in storefront tab keys. These map to the fixed sections in
# index.html and are never removed from nav_config['tabs'] — only
# reordered or hidden. Custom pages (Faqet Shtesë) are referenced as
# "page:<slug>" and are free-form (added/removed by the pages feature).
BUILTIN_NAV_KEYS = [
    'overview', 'services', 'menu', 'orders',
    'rentals', 'reviews', 'blog', 'contact',
]



def _clean_nav_config(value):
    if value in (None, {}):
        return {}
    if not isinstance(value, dict):
        raise serializers.ValidationError("nav_config must be an object.")
    tabs = value.get('tabs', [])
    if not isinstance(tabs, list):
        raise serializers.ValidationError("nav_config.tabs must be a list.")
    seen_builtin = set()
    cleaned = []
    for entry in tabs:
        if not isinstance(entry, dict) or 'key' not in entry:
            raise serializers.ValidationError(
                "Each nav_config.tabs entry must be an object with a 'key'."
            )
        key = entry['key']
        if not isinstance(key, str):
            raise serializers.ValidationError("nav_config.tabs[].key must be a string.")
        if not (key in BUILTIN_NAV_KEYS or key.startswith('page:')):
            raise serializers.ValidationError(f"Unknown nav key: {key}")
        if key in BUILTIN_NAV_KEYS:
            seen_builtin.add(key)
        cleaned.append({'key': key, 'hidden': bool(entry.get('hidden', False))})
    # Built-in tabs can be reordered/hidden but never dropped from the list
    # entirely — silently re-append any missing ones at the end so a
    # stale/partial payload can't make a section unreachable.
    for key in BUILTIN_NAV_KEYS:
        if key not in seen_builtin:
            cleaned.append({'key': key, 'hidden': False})
    return {'tabs': cleaned}


def _check_background_text_contrast(serializer, attrs):
    """
    background_color/text_color are model-level validated too (Tenant.clean(),
    for Django-admin saves), but DRF's ModelSerializer never calls
    instance.full_clean() on its own, so the API path needs its own check.
    Handles PATCH: a request updating only one of the two fields is merged
    against the other's current DB value before checking.
    """
    instance = serializer.instance
    bg  = attrs.get('background_color', getattr(instance, 'background_color', None))
    txt = attrs.get('text_color', getattr(instance, 'text_color', None))
    try:
        validate_color_contrast(bg, txt)
    except DjangoValidationError as exc:
        raise serializers.ValidationError({'text_color': exc.messages})
    return attrs


class TenantLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = TenantLocation
        fields = [
            'id', 'name', 'address', 'city', 'phone', 'email',
            'latitude', 'longitude', 'is_primary', 'is_active',
        ]


class TenantFeatureSerializer(serializers.ModelSerializer):
    class Meta:
        model = TenantFeature
        fields = ['key', 'value', 'is_custom_grant']


class TenantPublicSerializer(serializers.ModelSerializer):
    logo_url              = serializers.SerializerMethodField()
    locations             = TenantLocationSerializer(many=True, read_only=True)
    features              = TenantFeatureSerializer(many=True, read_only=True)
    business_type_display = serializers.SerializerMethodField()

    class Meta:
        model = Tenant
        fields = [
            'id', 'name', 'slug', 'site_title', 'tagline',
            'business_type', 'business_type_display',
            'logo_url', 'primary_color', 'accent_color', 'font_family',
            'font_heading', 'font_body', 'border_radius',
            'background_color', 'text_color',
            # LOW-2 FIX: reply_from_email removed — it's an internal sending address
            # not intended for public exposure. It remains in TenantSettingsSerializer
            # (authenticated owner) and TenantAdminSerializer (superadmin).
            'email', 'phone', 'whatsapp', 'address', 'city', 'country',
            'latitude', 'longitude',
            'business_hours', 'facebook', 'instagram', 'tiktok', 'website',
            'story', 'founded_year', 'meta_description',
            # MED-4 FIX: 'plan', 'trial_days_remaining', and 'trial_expired' removed.
            # TenantPublicSerializer is served by TenantInfoView (AllowAny) — any
            # anonymous visitor, competitor, or scraper can read it. Subscription tier
            # and trial status are internal billing data; leaking them via a public
            # endpoint lets competitors identify trial tenants for targeted outreach.
            # These fields remain available in TenantSettingsSerializer (IsTenantOwner)
            # which the owner SPA reads after authentication.
            # MED-3 FIX: 'onboarding_step' and 'onboarding_complete' removed.
            # Internal product-adoption state has no legitimate use for anonymous
            # visitors; exposing it lets competitors identify businesses with
            # incomplete setups for targeted outreach.
            'listed_on_marketplace', 'marketplace_description',
            # M-2 FIX: 'referral_code' removed. TenantPublicSerializer is served by
            # TenantInfoView (AllowAny) — any anonymous visitor, competitor, or scraper
            # can enumerate all referral codes via paginated /api/tenants/marketplace/
            # + /api/tenants/info/?slug=... calls. Referral codes are currency (€10
            # credit per conversion); exposing them enables fraudulent attribution and
            # referral budget exhaustion. The code is still available in
            # TenantSettingsSerializer (IsTenantOwner) for the owner's settings page.
            'locations', 'features',
            'nav_config',
        ]

    def get_logo_url(self, obj):
        if obj.logo:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.logo.url)
        return None

    def get_business_type_display(self, obj):
        return obj.get_business_type_display()


class TenantSettingsSerializer(serializers.ModelSerializer):
    trial_days_remaining = serializers.IntegerField(read_only=True)
    trial_expired = serializers.BooleanField(read_only=True)
    features = TenantFeatureSerializer(many=True, read_only=True)
    # Expose only whether a Stripe customer exists, never the raw ID —
    # the frontend just needs to know whether to show "Manage Billing"
    # (existing customer) or "Upgrade" (no customer yet) buttons.
    has_billing_account = serializers.SerializerMethodField()

    class Meta:
        model = Tenant
        fields = [
            'name', 'site_title', 'tagline', 'business_type',
            'logo', 'primary_color', 'accent_color', 'font_family',
            'font_heading', 'font_body', 'border_radius',
            'background_color', 'text_color',
            'email', 'reply_from_email', 'phone', 'whatsapp', 'address', 'city', 'country',
            'latitude', 'longitude',
            'business_hours', 'facebook', 'instagram', 'tiktok', 'website',
            'story', 'founded_year', 'meta_description', 'meta_keywords',
            'onboarding_step', 'onboarding_complete',
            'listed_on_marketplace', 'marketplace_description',
            'plan', 'trial_ends_at', 'trial_days_remaining', 'trial_expired',
            'has_billing_account', 'features', 'nav_config', 'currency',
            'accepts_online_payments',
        ]
        read_only_fields = [
            'plan', 'trial_ends_at', 'trial_days_remaining', 'trial_expired',
            'has_billing_account', 'features',
            # currency is locked to ALL platform-wide (see the comment on
            # Tenant.currency in tenants/models.py) — kept in `fields` above
            # so it's still visible in the settings response for
            # transparency, but no longer owner-editable. EUR/USD are
            # offered to a tenant's own customers only at Stripe checkout
            # time via payments.views.create_booking_checkout's pay_currency
            # param, not here.
            'currency',
        ]

    def get_has_billing_account(self, obj):
        return bool(obj.stripe_customer_id)

    def validate_nav_config(self, value):

        return _clean_nav_config(value)

    def validate(self, attrs):
        return _check_background_text_contrast(self, attrs)


class TenantAdminSerializer(serializers.ModelSerializer):
    locations            = TenantLocationSerializer(many=True, read_only=True)
    trial_days_remaining = serializers.IntegerField(read_only=True)
    trial_expired        = serializers.BooleanField(read_only=True)
    # HIGH-3 FIX: Replace fields = '__all__' with an explicit list.
    # '__all__' was leaking stripe_customer_id and stripe_subscription_id in
    # bulk list responses and individual tenant responses via the superadmin
    # API. These are internal billing references that should not be exposed
    # at the API layer; a boolean has_billing_account flag is sufficient
    # (matching the pattern already used in TenantSettingsSerializer).
    # Explicit enumeration also prevents future model fields from being
    # automatically exposed when migrations add them.
    has_billing_account  = serializers.SerializerMethodField()

    def get_has_billing_account(self, obj):
        return bool(obj.stripe_customer_id)

    class Meta:
        model = Tenant
        fields = [
            'id', 'name', 'slug', 'site_title', 'tagline', 'business_type',
            'logo', 'primary_color', 'accent_color', 'font_family',
            'font_heading', 'font_body', 'border_radius',
            'background_color', 'text_color',
            'email', 'reply_from_email', 'phone', 'whatsapp', 'address',
            'city', 'country', 'business_hours', 'latitude', 'longitude',
            'facebook', 'instagram', 'tiktok', 'website',
            'story', 'founded_year',
            'plan', 'is_active', 'trial_ends_at', 'trial_warning_sent_at',
            'has_billing_account', 'currency', 'accepts_online_payments',
            'referral_code', 'referred_by', 'referral_credits',
            'listed_on_marketplace', 'marketplace_description',
            'meta_description', 'meta_keywords',
            'onboarding_step', 'onboarding_complete',
            'created_at', 'updated_at',
            # computed fields
            'locations', 'trial_days_remaining', 'trial_expired',
        ]
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate(self, attrs):
        return _check_background_text_contrast(self, attrs)


class TenantSignupSerializer(serializers.Serializer):
    business_name   = serializers.CharField(max_length=200)
    slug            = serializers.SlugField(max_length=80)
    business_type   = serializers.ChoiceField(choices=[c[0] for c in BUSINESS_TYPE_CHOICES])
    # Lets the tenant pick their own plan at signup instead of always being
    # forced onto the trial. Optional -- defaults to the 14-day trial so
    # existing clients that don't send this field keep working unchanged.
    plan            = serializers.ChoiceField(choices=[c[0] for c in PLAN_CHOICES], required=False, default=PLAN_TRIAL)
    owner_email     = serializers.EmailField()
    owner_password  = serializers.CharField(min_length=8, write_only=True)
    owner_name      = serializers.CharField(max_length=200)
    referral_code   = serializers.CharField(max_length=20, required=False, allow_blank=True)

    # L-3 FIX: Single source of truth — use Tenant._RESERVED_SLUGS directly
    # instead of maintaining a duplicate frozenset here. Any slug added to the
    # model's set is automatically enforced at the API layer as well.

    def validate_slug(self, value):
        if value in Tenant._RESERVED_SLUGS:
            raise serializers.ValidationError(
                'This subdomain is reserved and cannot be used. Please choose another.'
            )
        if Tenant.objects.filter(slug=value).exists():
            raise serializers.ValidationError('This subdomain is already taken.')
        return value

    def validate_owner_email(self, value):
        from accounts.models import User
        # M-1 FIX: normalize to lowercase so the duplicate-email check matches
        # regardless of case, and the stored user is created with a consistent
        # email that will always match on login.
        value = value.strip().lower()
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError('An account with this email already exists.')
        return value

    def validate_owner_password(self, value):
        # H-1 FIX: Enforce AUTH_PASSWORD_VALIDATORS for the tenant owner password.
        # Previously only min_length=8 was checked, allowing weak passwords like
        # 'password1' or '12345678'. The owner is the most privileged account on
        # the platform (full tenant admin, billing, staff management), so the full
        # validator suite (CommonPasswordValidator, NumericPasswordValidator,
        # UserAttributeSimilarityValidator) must run — identical to RegisterSerializer,
        # ChangePasswordView, and PasswordResetConfirmView.
        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError as DjangoValidationError
        from accounts.models import User
        temp = User(
            email=self.initial_data.get('owner_email', ''),
            full_name=self.initial_data.get('owner_name', ''),
        )
        try:
            validate_password(value, user=temp)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))
        return value

    def validate_referral_code(self, value):
        if value:
            if not Tenant.objects.filter(referral_code=value).exists():
                raise serializers.ValidationError('Invalid referral code.')
        return value


# ── Marketplace ───────────────────────────────────────────────────────────────

class MarketplaceTenantSerializer(serializers.ModelSerializer):
    """Lean serializer for the public discovery directory."""
    logo_url              = serializers.SerializerMethodField()
    business_type_display = serializers.SerializerMethodField()

    class Meta:
        model = Tenant
        fields = [
            'slug', 'name', 'tagline', 'business_type', 'business_type_display',
            'city', 'logo_url', 'primary_color',
            'phone', 'whatsapp', 'facebook', 'instagram',
            # H-3 FIX: 'plan' removed. This is a public AllowAny endpoint — exposing
            # subscription tier (trial/starter/pro/enterprise) lets competitors identify
            # trial tenants for targeted outreach. Same reasoning applied to
            # TenantPublicSerializer (MED-4 FIX). Plan data is available only to the
            # owner via TenantSettingsSerializer (IsTenantOwner).
            'marketplace_description',
        ]

    def get_logo_url(self, obj):
        if obj.logo:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.logo.url)
        return None

    def get_business_type_display(self, obj):
        return obj.get_business_type_display()


# ── Feature grant (superadmin) ────────────────────────────────────────────────

class FeatureGrantSerializer(serializers.Serializer):
    key   = serializers.CharField(max_length=100)
    value = serializers.CharField(max_length=200)


# ── Location (tenant-side) ────────────────────────────────────────────────────

class TenantLocationCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = TenantLocation
        fields = [
            'name', 'address', 'city', 'phone', 'email',
            'latitude', 'longitude', 'is_primary', 'is_active',
        ]


# ── Referral ──────────────────────────────────────────────────────────────────

class TenantReferralSerializer(serializers.ModelSerializer):
    referred_slug = serializers.CharField(source='referred.slug', read_only=True)

    class Meta:
        model = TenantReferral
        fields = ['id', 'referred_slug', 'credit_amount', 'applied', 'created_at']


# ── Credit ledger ─────────────────────────────────────────────────────────────

class CreditLedgerSerializer(serializers.ModelSerializer):
    """
    Read-only display serializer for CreditLedger entries (e.g. GET
    /api/tenants/credits/balance/). Previously this was a plain inline
    class in views.py with a hand-rolled `to_dict()` — not a real DRF
    serializer, so it had no field validation/context and couldn't be
    reused. Promoted to a proper ModelSerializer here.
    """
    referral_id = serializers.SerializerMethodField()

    class Meta:
        model = CreditLedger
        fields = ['id', 'amount', 'event', 'description', 'created_at', 'referral_id']
        read_only_fields = fields

    def get_referral_id(self, obj):
        return str(obj.referral_id) if obj.referral_id else None
