from django.contrib import admin
from django.utils.html import format_html
from .models import Tenant, TenantFeature


class TenantFeatureInline(admin.TabularInline):
    model = TenantFeature
    extra = 0


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'business_type', 'plan', 'is_active', 'city', 'created_at')
    list_filter = ('plan', 'is_active', 'business_type', 'city')
    search_fields = ('name', 'slug', 'email')
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ('id', 'created_at', 'updated_at', 'stripe_customer_id', 'stripe_subscription_id')
    inlines = [TenantFeatureInline]
    actions = ['activate_tenants', 'deactivate_tenants']

    fieldsets = (
        ('Identity', {'fields': ('id', 'name', 'slug', 'site_title', 'tagline', 'business_type')}),
        ('Branding', {'fields': ('logo', 'primary_color', 'accent_color', 'font_family')}),
        ('Contact', {'fields': ('email', 'phone', 'whatsapp', 'address', 'city', 'country', 'business_hours')}),
        ('Social', {'fields': ('facebook', 'instagram', 'tiktok', 'website')}),
        ('Content', {'fields': ('story', 'founded_year')}),
        ('Plan & Billing', {'fields': ('plan', 'is_active', 'trial_ends_at', 'stripe_customer_id', 'stripe_subscription_id')}),
        ('SEO', {'fields': ('meta_description', 'meta_keywords')}),
        ('Timestamps', {'fields': ('created_at', 'updated_at')}),
    )

    def activate_tenants(self, request, queryset):
        queryset.update(is_active=True)
    activate_tenants.short_description = 'Activate selected tenants'

    def deactivate_tenants(self, request, queryset):
        queryset.update(is_active=False)
    deactivate_tenants.short_description = 'Deactivate selected tenants'
