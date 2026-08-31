import datetime
import unicodedata

from django.conf import settings
from django.contrib import admin
from django.core.cache import cache
from django.core.mail import send_mail
from django.db.models import Q
from django.utils import timezone
from django.utils.html import format_html

from .models import Tenant, TenantFeature, TenantLocation, TenantReferral, TrialTenant, PLAN_TRIAL, TRIAL_DAYS


def _normalize_city(value):
    """Strip diacritics + case so 'Durrës'/'Durres' and 'Tiranë'/'Tirane'
    collapse to the same bucket. Same normalization Albanian users commonly
    type both ways when typing without special-character keyboard layouts."""
    if not value:
        return ''
    decomposed = unicodedata.normalize('NFKD', value)
    return ''.join(c for c in decomposed if not unicodedata.combining(c)).strip().lower()


class NormalizedCityFilter(admin.SimpleListFilter):
    """
    Replaces the raw `city` list_filter, which — because city is free-text —
    rendered every distinct spelling as its own entry (Durres/Durrës,
    Tirane/Tiranë each separately), plus a blank/unlabeled option for empty
    strings. This groups spellings that normalize to the same city and adds
    an explicit "No city set" bucket instead of a silent blank link.
    """
    title = 'city'
    parameter_name = 'city_norm'

    def lookups(self, request, model_admin):
        raw_cities = (
            Tenant.objects.exclude(city='')
            .values_list('city', flat=True).distinct()
        )
        by_norm = {}
        for city in raw_cities:
            norm = _normalize_city(city)
            has_diacritics = any(ord(ch) > 127 for ch in city)
            # Prefer whichever spelling actually has diacritics (Durrës over
            # Durres) as the display label when both variants exist.
            if norm not in by_norm or has_diacritics:
                by_norm[norm] = city
        options = [(norm, label) for norm, label in sorted(by_norm.items(), key=lambda kv: kv[1])]
        options.append(('__blank__', 'No city set'))
        return options

    def queryset(self, request, queryset):
        value = self.value()
        if not value:
            return queryset
        if value == '__blank__':
            return queryset.filter(city='')
        matches = [
            c for c in queryset.values_list('city', flat=True).distinct()
            if _normalize_city(c) == value
        ]
        return queryset.filter(city__in=matches)


BUSINESS_CATEGORY_GROUPS = {
    'retail': ('Retail', [
        'market', 'pharmacy', 'electronics', 'clothing', 'organic', 'bookstore',
        'jewelry', 'toy_store', 'sports_shop', 'furniture', 'petrol_station',
    ]),
    'food': ('Food & Hospitality', [
        'restaurant', 'hotel', 'bar', 'delivery_kitchen', 'bakery', 'catering',
    ]),
    'rentals': ('Rentals', [
        'car_rental', 'property_rental', 'equipment_rental', 'boat_rental',
    ]),
    'health_beauty': ('Health & Beauty', [
        'barbershop', 'spa', 'gym', 'clinic', 'tattoo', 'veterinary', 'optician',
    ]),
    'services': ('Services', [
        'auto_repair', 'cleaning', 'lawyer', 'accounting', 'event_agency',
        'photography', 'printing', 'travel_agency', 'funeral_home', 'security',
    ]),
    'education': ('Education', [
        'language_school', 'tutoring', 'driving_school', 'coding_bootcamp', 'nursery',
    ]),
    'professional': ('Professional & B2B', [
        'real_estate', 'construction', 'architecture', 'import_export', 'agro',
        'transport', 'it_company', 'marketing_agency',
    ]),
}


class BusinessCategoryFilter(admin.SimpleListFilter):
    """
    business_type has ~50 choices, which made the plain list_filter dropdown
    a single unbroken scroll with no way to narrow by category. This adds a
    category-level filter (mirroring the grouping already used as section
    comments in BUSINESS_TYPE_CHOICES) that sits above the existing
    business_type filter rather than replacing it — so an admin can narrow
    to "Food & Hospitality" first, then to "Hotel / Guesthouse" specifically.
    """
    title = 'business category'
    parameter_name = 'business_category'

    def lookups(self, request, model_admin):
        return [(key, label) for key, (label, _types) in BUSINESS_CATEGORY_GROUPS.items()]

    def queryset(self, request, queryset):
        value = self.value()
        if not value or value not in BUSINESS_CATEGORY_GROUPS:
            return queryset
        return queryset.filter(business_type__in=BUSINESS_CATEGORY_GROUPS[value][1])


class TrialStatusFilter(admin.SimpleListFilter):
    """
    trial_status/trial_days_remaining are computed properties (plan +
    trial_ends_at), so they weren't filterable at all before — there was no
    way to pull up e.g. "all expired trials that still haven't been
    deactivated" without opening the Trial dashboard and eyeballing every
    row's countdown. This adds queryset-level equivalents of that logic.
    """
    title = 'trial status'
    parameter_name = 'trial_status'

    def lookups(self, request, model_admin):
        return [
            ('active', 'Trial — active'),
            ('expiring_soon', 'Trial — expiring in ≤3 days'),
            ('expired', 'Trial — expired (not yet converted/deactivated)'),
            ('not_trial', 'Not on trial'),
        ]

    def queryset(self, request, queryset):
        value = self.value()
        now = timezone.now()
        if value == 'active':
            return queryset.filter(plan=PLAN_TRIAL).filter(
                Q(trial_ends_at__isnull=True) | Q(trial_ends_at__gt=now)
            )
        if value == 'expiring_soon':
            return queryset.filter(
                plan=PLAN_TRIAL,
                trial_ends_at__gt=now,
                trial_ends_at__lte=now + datetime.timedelta(days=3),
            )
        if value == 'expired':
            return queryset.filter(plan=PLAN_TRIAL, trial_ends_at__lt=now)
        if value == 'not_trial':
            return queryset.exclude(plan=PLAN_TRIAL)
        return queryset


class HasOwnerFilter(admin.SimpleListFilter):
    """
    Surfaces tenants with no linked owner User row — previously the only way
    to spot one of these (a signup that silently failed to create the owner
    account, per TenantUserInline's docstring above) was opening each tenant
    individually and checking the Linked users inline by hand.
    """
    title = 'owner account'
    parameter_name = 'has_owner'

    def lookups(self, request, model_admin):
        return [('yes', 'Has owner'), ('no', 'Missing owner (needs attention)')]

    def queryset(self, request, queryset):
        value = self.value()
        if value == 'yes':
            return queryset.filter(users__role='owner').distinct()
        if value == 'no':
            return queryset.exclude(users__role='owner').distinct()
        return queryset


class BillingLinkedFilter(admin.SimpleListFilter):
    """Whether a Stripe subscription is actually attached — useful for
    catching paid-plan tenants (plan=pro/enterprise) with no
    stripe_subscription_id, which usually means the plan was set manually
    in admin rather than through a real checkout."""
    title = 'stripe subscription'
    parameter_name = 'has_stripe'

    def lookups(self, request, model_admin):
        return [('yes', 'Linked'), ('no', 'Not linked')]

    def queryset(self, request, queryset):
        value = self.value()
        if value == 'yes':
            return queryset.exclude(stripe_subscription_id='').exclude(stripe_subscription_id__isnull=True)
        if value == 'no':
            return queryset.filter(Q(stripe_subscription_id='') | Q(stripe_subscription_id__isnull=True))
        return queryset


class OnboardingProgressFilter(admin.SimpleListFilter):
    """
    onboarding_complete is a boolean, but onboarding_step is the actual
    funnel counter behind it — with it un-filterable, there was no way to
    see *where* incomplete signups stall (e.g. everyone stuck at step 1
    vs. spread evenly) without exporting the whole incomplete set and
    sorting by hand. This buckets the step count into funnel stages.
    """
    title = 'onboarding progress'
    parameter_name = 'onboarding_progress'

    # Buckets are deliberately coarse — enough to spot where the funnel
    # leaks without hardcoding the exact number of onboarding steps here
    # (that lives in the onboarding flow itself and can change).
    _BUCKETS = (
        ('not_started', 'Not started (step 0)', lambda step: step == 0),
        ('early', 'Early (steps 1–2)', lambda step: 1 <= step <= 2),
        ('mid', 'Mid (steps 3–4)', lambda step: 3 <= step <= 4),
        ('late', 'Late (step 5+, not yet complete)', lambda step: step >= 5),
    )

    def lookups(self, request, model_admin):
        return [(key, label) for key, label, _pred in self._BUCKETS]

    def queryset(self, request, queryset):
        value = self.value()
        if not value:
            return queryset
        queryset = queryset.filter(onboarding_complete=False)
        if value == 'not_started':
            return queryset.filter(onboarding_step=0)
        if value == 'early':
            return queryset.filter(onboarding_step__in=[1, 2])
        if value == 'mid':
            return queryset.filter(onboarding_step__in=[3, 4])
        if value == 'late':
            return queryset.filter(onboarding_step__gte=5)
        return queryset


class ReferralSourceFilter(admin.SimpleListFilter):
    """Organic signup vs. arrived via another tenant's referral link —
    previously only visible one tenant at a time via the referred_by field
    on the change form."""
    title = 'referral source'
    parameter_name = 'referral_source'

    def lookups(self, request, model_admin):
        return [('referred', 'Referred by another tenant'), ('organic', 'Organic (no referrer)')]

    def queryset(self, request, queryset):
        value = self.value()
        if value == 'referred':
            return queryset.exclude(referred_by__isnull=True)
        if value == 'organic':
            return queryset.filter(referred_by__isnull=True)
        return queryset


class MarketplaceDataQualityFilter(admin.SimpleListFilter):
    """
    listed_on_marketplace just says whether a tenant *should* appear in the
    public directory — it says nothing about whether the listing actually
    has enough content to be worth showing (no logo, no blurb reads as a
    broken/empty card to a visitor). Only meaningful for listed tenants, so
    it's scoped to listed_on_marketplace=True rather than offered globally.
    """
    title = 'marketplace listing quality'
    parameter_name = 'marketplace_quality'

    def lookups(self, request, model_admin):
        return [
            ('missing_description', 'Listed, missing description'),
            ('missing_logo', 'Listed, missing logo'),
            ('incomplete', 'Listed, missing description or logo'),
        ]

    def queryset(self, request, queryset):
        value = self.value()
        if not value:
            return queryset
        queryset = queryset.filter(listed_on_marketplace=True)
        no_description = Q(marketplace_description='')
        no_logo = Q(logo='') | Q(logo__isnull=True)
        if value == 'missing_description':
            return queryset.filter(no_description)
        if value == 'missing_logo':
            return queryset.filter(no_logo)
        if value == 'incomplete':
            return queryset.filter(no_description | no_logo)
        return queryset


class GeolocatedFilter(admin.SimpleListFilter):
    """Whether lat/long are set — anything that plots tenants on a map
    (marketplace directory, location pickers) silently drops rows missing
    these, which was previously only discoverable by opening a tenant and
    noticing the coordinate fields were blank."""
    title = 'map coordinates'
    parameter_name = 'has_coords'

    def lookups(self, request, model_admin):
        return [('yes', 'Has coordinates'), ('no', 'Missing coordinates')]

    def queryset(self, request, queryset):
        value = self.value()
        if value == 'yes':
            return queryset.filter(latitude__isnull=False, longitude__isnull=False)
        if value == 'no':
            return queryset.filter(Q(latitude__isnull=True) | Q(longitude__isnull=True))
        return queryset


def apply_activation_side_effects(tenant, was_active, actor=None):
    """
    Ported from the retired SuperadminTenantDetailView.perform_update()
    (tenants/views.py, removed — django-admin is now the only surface that
    flips Tenant.is_active). Runs the same activation-gated trial-clock
    start and owner-notification email that API path used to run, so that
    toggling is_active here — via a bulk action or a single change-form
    save — has identical side effects to the old REST endpoint.

    was_active must be the value BEFORE this save/update, captured by the
    caller (queryset.update() has no signal hook, so this cannot be
    inferred from the instance after the fact).
    """
    if was_active == tenant.is_active:
        return  # no transition, nothing to do

    if not was_active and tenant.is_active and tenant.plan == PLAN_TRIAL and not tenant.trial_ends_at:
        tenant.trial_ends_at = timezone.now() + datetime.timedelta(days=TRIAL_DAYS)
        tenant.save(update_fields=['trial_ends_at'])

    try:
        from accounts.models import User as _User
        owner = _User.objects.filter(tenant=tenant, role='owner').first()
        if owner:
            if tenant.is_active:
                tenant_url = (
                    f"https://{tenant.slug}.bizal.al"
                    if not settings.DEBUG
                    else f"http://{tenant.slug}.localhost:8001/"
                )
                send_mail(
                    subject='Llogaria juaj BizAL është aktivizuar! 🎉',
                    message=(
                        f'Përshëndetje {owner.full_name},\n\n'
                        f'Lajm i mirë! Llogaria juaj për "{tenant.name}" është aktivizuar.\n\n'
                        f'Mund të hyni në panelin tuaj tani:\n{tenant_url}\n\n'
                        f'Nëse keni pyetje, shkruani te support@bizal.al\n\n'
                        f'BizAL Team'
                    ),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[owner.email],
                    fail_silently=True,
                )
            else:
                send_mail(
                    subject='Llogaria juaj BizAL është çaktivizuar',
                    message=(
                        f'Përshëndetje {owner.full_name},\n\n'
                        f'Llogaria juaj për "{tenant.name}" është çaktivizuar nga ekipi i BizAL.\n\n'
                        f'Nëse mendoni se kjo është gabim, ju lutemi kontaktoni support@bizal.al\n\n'
                        f'BizAL Team'
                    ),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[owner.email],
                    fail_silently=True,
                )
    except Exception:
        pass  # Email nuk duhet të bllokojë update-in


def _bulk_deactivate_tenants(queryset, request):
    """
    Shared by TenantAdmin.deactivate_tenants and TrialTenantAdmin.deactivate_tenants
    so the two admin dashboards can't drift out of sync on what "deactivate" does.
    (Previously TrialTenantAdmin had its own copy that only flipped is_active and
    cleared the cache — no deactivation email via apply_activation_side_effects,
    no activity.log_activity entry, so deactivating from the Trial dashboard left
    no audit trail and never notified the owner.)
    """
    was_active_by_id = dict(queryset.values_list('id', 'is_active'))
    updated = queryset.update(is_active=False)
    # queryset.update() bypasses save(), so the tenant cache is never
    # invalidated as a side effect — has to be done explicitly here.
    for t in queryset:
        cache.delete(f'tenant:{t.slug}')
        apply_activation_side_effects(t, was_active_by_id.get(t.id, True))
    try:
        from activity.utils import log_activity
        for t in queryset:
            log_activity(
                tenant=t, actor=request.user,
                verb='tenant.deactivated',
                description='Bulk deactivated by superadmin',
                target_type='tenant', target_id=t.id,
            )
    except Exception:
        pass
    return updated


def _bulk_convert_to_pro(queryset, request):
    """
    Shared by TenantAdmin.convert_to_pro and TrialTenantAdmin.convert_to_pro, for
    the same reason as _bulk_deactivate_tenants above — TrialTenantAdmin's copy
    updated the plan and cache but skipped the log_activity call.
    """
    tenant_ids = list(queryset.values_list('id', flat=True))
    for t in queryset:
        t.plan = 'pro'
        t.save()
        cache.delete(f'tenant:{t.slug}')
    try:
        from activity.utils import log_activity
        # Re-fetch by id rather than re-using `queryset`: for callers whose
        # queryset filters on plan (e.g. TrialTenantAdmin's plan='trial'
        # get_queryset), the plan='pro' save above would make re-iterating
        # the original queryset return zero rows.
        for t in Tenant.objects.filter(id__in=tenant_ids):
            log_activity(
                tenant=t, actor=request.user,
                verb='tenant.plan_changed',
                description='Plan converted to Pro by superadmin',
                target_type='tenant', target_id=t.id,
            )
    except Exception:
        pass
    return len(tenant_ids)


class TenantFeatureInline(admin.TabularInline):
    model = TenantFeature
    extra = 0
    fields = ('key', 'value', 'is_custom_grant')
    readonly_fields = ('is_custom_grant',)


class TenantLocationInline(admin.TabularInline):
    model = TenantLocation
    extra = 0
    fields = ('name', 'city', 'address', 'phone', 'is_primary', 'is_active')


class TenantUserInline(admin.TabularInline):
    """
    Read-only view of the accounts.User rows linked to this tenant (owner,
    staff, managers). TenantAdmin previously had no way to confirm a tenant's
    owner account actually exists without leaving the page and searching the
    separate Users admin by tenant — which, combined with a freshly-signed-up
    tenant showing mostly blank fields until onboarding is finished, made a
    perfectly normal "owner exists, onboarding just isn't done yet" tenant
    look like signup had silently failed to create the owner at all.
    """
    from accounts.models import User
    model = User
    fk_name = 'tenant'
    extra = 0
    fields = ('email', 'full_name', 'role', 'is_active', 'created_at')
    readonly_fields = ('email', 'full_name', 'role', 'is_active', 'created_at')
    can_delete = False
    verbose_name = 'Linked user'
    verbose_name_plural = 'Linked users (owner / staff)'

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'business_type', 'plan', 'owner_email', 'onboarding_complete', 'is_active', 'trial_status', 'city', 'created_at')
    # Reordered + expanded: status filters first (what an admin scans for
    # daily — activity/onboarding/trial health), then classification
    # (plan/category/type/city), then billing/marketplace last. The plain
    # `business_type` filter is kept alongside the new category filter
    # rather than replaced by it, so a specific type is still one click away
    # once narrowed by category.
    list_filter  = (
        'is_active', 'onboarding_complete', OnboardingProgressFilter, HasOwnerFilter,
        TrialStatusFilter, 'plan', BusinessCategoryFilter, 'business_type',
        NormalizedCityFilter, 'currency', 'accepts_online_payments',
        BillingLinkedFilter, 'listed_on_marketplace', MarketplaceDataQualityFilter,
        GeolocatedFilter, ReferralSourceFilter,
    )
    search_fields = ('name', 'slug', 'email', 'referral_code', 'users__email')
    date_hierarchy = 'created_at'
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ('id', 'created_at', 'updated_at', 'stripe_customer_id',
                       'stripe_subscription_id', 'referral_code', 'referral_credits')
    inlines = [TenantUserInline, TenantFeatureInline, TenantLocationInline]
    actions = ['activate_tenants', 'deactivate_tenants', 'convert_to_pro', 'list_on_marketplace']
    list_per_page = 50

    def get_queryset(self, request):
        # owner_email() below does a query per row (obj.users.filter(...)).
        # Prefetching the reverse FK once here turns that from N+1 queries
        # into 2 for a full page of results — same output, no per-row hit.
        return super().get_queryset(request).prefetch_related('users')

    def owner_email(self, obj):
        owners = sorted((u for u in obj.users.all() if u.role == 'owner'), key=lambda u: u.created_at)
        return owners[0].email if owners else '— nuk u gjet —'
    owner_email.short_description = 'Owner'

    # FIX #6: Disable hard-delete from the admin to prevent accidental
    # CASCADE deletion of all tenant data. Deactivation is the correct
    # workflow; actual deletion should go through a deliberate data-export
    # + hard-delete script run by a senior engineer.
    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        # Single-tenant edits via the change form also flip is_active
        # (it's a normal field in the "Plan & Billing" fieldset below), not
        # just the bulk actions. Capture the pre-save state so the same
        # trial-clock/email side effects fire either way.
        was_active = None
        if change:
            was_active = Tenant.objects.filter(pk=obj.pk).values_list('is_active', flat=True).first()
        super().save_model(request, obj, form, change)
        cache.delete(f'tenant:{obj.slug}')
        if was_active is not None:
            apply_activation_side_effects(obj, was_active)

    fieldsets = (
        ('Identity',     {'fields': ('id', 'name', 'slug', 'site_title', 'tagline', 'business_type')}),
        ('Branding',     {'fields': ('logo', 'primary_color', 'accent_color', 'font_family',
                                      'font_heading', 'font_body', 'border_radius',
                                      'background_color', 'text_color')}),
        ('Contact',      {'fields': ('email', 'phone', 'whatsapp', 'address', 'city', 'country',
                                     'latitude', 'longitude', 'business_hours')}),
        ('Social',       {'fields': ('facebook', 'instagram', 'tiktok', 'website')}),
        ('Content',      {'fields': ('story', 'founded_year')}),
        ('Plan & Billing', {'fields': ('plan', 'is_active', 'trial_ends_at',
                                       'stripe_customer_id', 'stripe_subscription_id')}),
        ('Referral',     {'fields': ('referral_code', 'referred_by', 'referral_credits')}),
        ('Marketplace',  {'fields': ('listed_on_marketplace', 'marketplace_description')}),
        ('SEO',          {'fields': ('meta_description', 'meta_keywords')}),
        ('Timestamps',   {'fields': ('created_at', 'updated_at')}),
    )

    def trial_status(self, obj):
        if obj.plan != 'trial':
            return '—'
        if obj.trial_expired:
            return '⛔ Expired'
        days = obj.trial_days_remaining
        return f'⏳ {days}d left'
    trial_status.short_description = 'Trial'

    def activate_tenants(self, request, queryset):
        # Capture pre-update state per tenant BEFORE the bulk .update() —
        # queryset.update() is a single UPDATE statement with no per-row
        # signal, so this is the only point where "was it inactive before"
        # is still knowable.
        was_active_by_id = dict(queryset.values_list('id', 'is_active'))
        updated = queryset.update(is_active=True)
        # FIX: queryset.update() bypasses save(), so TenantMiddleware's
        # 5-minute tenant cache was never invalidated here — unlike
        # SuperadminTenantDetailView.perform_update(), which does this
        # correctly for the REST API path. Without it, a tenant activated
        # here could still 404 for up to 5 minutes on stale cache.
        for t in queryset:
            cache.delete(f'tenant:{t.slug}')
            apply_activation_side_effects(t, was_active_by_id.get(t.id, False))
        self.message_user(request, f'{updated} tenant(s) activated.')
        # Log the bulk action
        try:
            from activity.utils import log_activity
            for t in queryset:
                log_activity(
                    tenant=t, actor=request.user,
                    verb='tenant.activated',
                    description='Bulk activated by superadmin',
                    target_type='tenant', target_id=t.id,
                )
        except Exception:
            pass
    activate_tenants.short_description = 'Activate selected tenants'

    def deactivate_tenants(self, request, queryset):
        # FIX: same cache-invalidation gap as activate_tenants above — this
        # one matters more, since a deactivated tenant stayed fully live for
        # up to 5 minutes after this action ran. Shared with
        # TrialTenantAdmin.deactivate_tenants — see _bulk_deactivate_tenants.
        updated = _bulk_deactivate_tenants(queryset, request)
        self.message_user(request, f'{updated} tenant(s) deactivated.')
    deactivate_tenants.short_description = 'Deactivate selected tenants'

    def convert_to_pro(self, request, queryset):
        # FIX: same cache-invalidation gap as activate/deactivate above.
        # request.tenant.plan (read by has_feature() everywhere) comes
        # from this cache, so without the delete here a tenant could
        # keep getting Starter-plan feature limits for up to 5 minutes
        # after being converted to Pro. Shared with
        # TrialTenantAdmin.convert_to_pro — see _bulk_convert_to_pro.
        count = _bulk_convert_to_pro(queryset, request)
        self.message_user(request, f'{count} tenant(s) converted to Pro.')
    convert_to_pro.short_description = 'Convert to Pro plan'

    def list_on_marketplace(self, request, queryset):
        updated = queryset.update(listed_on_marketplace=True)
        # FIX: same cache-invalidation gap as activate/deactivate/convert_to_pro
        # above. TenantMiddleware._get_tenant() caches listed_on_marketplace
        # for up to 5 minutes, so the public marketplace_list endpoint
        # wouldn't show a newly-listed tenant until the cache expired.
        for t in queryset:
            cache.delete(f'tenant:{t.slug}')
        self.message_user(request, f'{updated} tenant(s) listed on marketplace.')
        try:
            from activity.utils import log_activity
            for t in queryset:
                log_activity(
                    tenant=t, actor=request.user,
                    verb='tenant.listed_on_marketplace',
                    description='Listed on marketplace by superadmin',
                    target_type='tenant', target_id=t.id,
                )
        except Exception:
            pass
    list_on_marketplace.short_description = 'List on marketplace directory'


@admin.register(TenantLocation)
class TenantLocationAdmin(admin.ModelAdmin):
    list_display  = ('tenant', 'name', 'city', 'is_primary', 'is_active')
    list_filter   = ('is_primary', 'is_active')
    search_fields = ('tenant__name', 'name', 'city')


@admin.register(TrialTenant)
class TrialTenantAdmin(admin.ModelAdmin):
    """
    Read-mostly dashboard of tenants currently on the trial plan, sorted by
    expiry. Mirrors what SuperadminTrialSummaryView exposes to the JS panel,
    but lives natively in Django admin — same DB, no separate API surface.
    """
    list_display  = ('name', 'slug', 'city', 'days_left', 'trial_ends_at', 'created_at')
    list_filter   = ('city',)
    search_fields = ('name', 'slug', 'email')
    ordering      = ('trial_ends_at',)
    readonly_fields = ('id', 'name', 'slug', 'email', 'city', 'plan',
                       'created_at', 'updated_at', 'trial_ends_at')
    actions = ['extend_trial_7d', 'extend_trial_30d', 'convert_to_pro', 'deactivate_tenants']

    fieldsets = (
        ('Tenant', {'fields': ('id', 'name', 'slug', 'email', 'city')}),
        ('Trial', {'fields': ('plan', 'trial_ends_at', 'created_at', 'updated_at')}),
    )

    def has_add_permission(self, request):
        # Trials are created through signup, not from this dashboard.
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).filter(plan='trial')

    def days_left(self, obj):
        days = obj.trial_days_remaining
        if days is None:
            return '—'
        if days <= 0:
            return format_html('<span style="color:#8B1A1A;font-weight:600;">⛔ Expired</span>')
        if days <= 3:
            return format_html('<span style="color:#7A4010;font-weight:600;">⏳ {}d left</span>', days)
        return f'⏳ {days}d left'
    days_left.short_description = 'Trial status'

    def _extend(self, request, queryset, days):
        for t in queryset:
            base = t.trial_ends_at if t.trial_ends_at and t.trial_ends_at > timezone.now() else timezone.now()
            t.trial_ends_at = base + datetime.timedelta(days=days)
            t.save(update_fields=['trial_ends_at'])
            cache.delete(f'tenant:{t.slug}')
        self.message_user(request, f'Extended trial by {days} day(s) for {queryset.count()} tenant(s).')
        try:
            from activity.utils import log_activity
            for t in queryset:
                log_activity(
                    tenant=t, actor=request.user,
                    verb='tenant.trial_extended',
                    description=f'Trial extended by {days} day(s) via admin',
                    target_type='tenant', target_id=t.id,
                )
        except Exception:
            pass

    def extend_trial_7d(self, request, queryset):
        self._extend(request, queryset, 7)
    extend_trial_7d.short_description = 'Extend trial by 7 days'

    def extend_trial_30d(self, request, queryset):
        self._extend(request, queryset, 30)
    extend_trial_30d.short_description = 'Extend trial by 30 days'

    def convert_to_pro(self, request, queryset):
        # Shared with TenantAdmin.convert_to_pro so the two dashboards can't
        # drift apart again — see _bulk_convert_to_pro for what this adds
        # over the old local copy (activation email/log_activity entry).
        count = _bulk_convert_to_pro(queryset, request)
        self.message_user(request, f'{count} tenant(s) converted to Pro.')
    convert_to_pro.short_description = 'Convert to Pro plan'

    def deactivate_tenants(self, request, queryset):
        # Shared with TenantAdmin.deactivate_tenants — see
        # _bulk_deactivate_tenants for what this adds over the old local
        # copy (deactivation email/log_activity entry).
        updated = _bulk_deactivate_tenants(queryset, request)
        self.message_user(request, f'{updated} tenant(s) deactivated.')
    deactivate_tenants.short_description = 'Deactivate selected tenants'


@admin.register(TenantReferral)
class TenantReferralAdmin(admin.ModelAdmin):
    list_display  = ('referrer', 'referred', 'credit_amount', 'applied', 'created_at')
    list_filter   = ('applied',)
    actions       = ['apply_credits']

    def apply_credits(self, request, queryset):
        for ref in queryset.filter(applied=False):
            ref.apply_credit()
    apply_credits.short_description = 'Apply credits to referrers'