import datetime

from django.conf import settings
from django.contrib import admin
from django.core.cache import cache
from django.core.mail import send_mail
from django.utils import timezone
from django.utils.html import format_html

from .models import Tenant, TenantFeature, TenantLocation, TenantReferral, TrialTenant, PLAN_TRIAL, TRIAL_DAYS


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
    list_filter  = ('plan', 'is_active', 'onboarding_complete', 'business_type', 'city', 'listed_on_marketplace')
    search_fields = ('name', 'slug', 'email', 'referral_code', 'users__email')
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ('id', 'created_at', 'updated_at', 'stripe_customer_id',
                       'stripe_subscription_id', 'referral_code', 'referral_credits')
    inlines = [TenantUserInline, TenantFeatureInline, TenantLocationInline]
    actions = ['activate_tenants', 'deactivate_tenants', 'convert_to_pro', 'list_on_marketplace']

    def owner_email(self, obj):
        owner = obj.users.filter(role='owner').order_by('created_at').first()
        return owner.email if owner else '— nuk u gjet —'
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
        was_active_by_id = dict(queryset.values_list('id', 'is_active'))
        updated = queryset.update(is_active=False)
        # FIX: same cache-invalidation gap as activate_tenants above — this
        # one matters more, since a deactivated tenant stayed fully live for
        # up to 5 minutes after this action ran.
        for t in queryset:
            cache.delete(f'tenant:{t.slug}')
            apply_activation_side_effects(t, was_active_by_id.get(t.id, True))
        self.message_user(request, f'{updated} tenant(s) deactivated.')
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
    deactivate_tenants.short_description = 'Deactivate selected tenants'

    def convert_to_pro(self, request, queryset):
        for t in queryset:
            t.plan = 'pro'
            t.save()
            # FIX: same cache-invalidation gap as activate/deactivate above.
            # request.tenant.plan (read by has_feature() everywhere) comes
            # from this cache, so without the delete here a tenant could
            # keep getting Starter-plan feature limits for up to 5 minutes
            # after being converted to Pro.
            cache.delete(f'tenant:{t.slug}')
        try:
            from activity.utils import log_activity
            for t in queryset:
                log_activity(
                    tenant=t, actor=request.user,
                    verb='tenant.plan_changed',
                    description='Plan converted to Pro by superadmin',
                    target_type='tenant', target_id=t.id,
                )
        except Exception:
            pass
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
        for t in queryset:
            t.plan = 'pro'
            t.save()
            cache.delete(f'tenant:{t.slug}')
        self.message_user(request, f'{queryset.count()} tenant(s) converted to Pro.')
    convert_to_pro.short_description = 'Convert to Pro plan'

    def deactivate_tenants(self, request, queryset):
        updated = queryset.update(is_active=False)
        for t in queryset:
            cache.delete(f'tenant:{t.slug}')
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
