from django.contrib import admin

from .models import AnalyticsEvent


@admin.register(AnalyticsEvent)
class AnalyticsEventAdmin(admin.ModelAdmin):
    """
    Read-only browser for the tenant event log. These rows are written by
    analytics.utils.track() from frontend/backend code, not by hand — so
    editing/adding is disabled, matching the pattern used for payments.WebhookEvent.
    """
    list_display = ('created_at', 'tenant', 'event_type', 'page')
    list_filter = ('event_type', 'tenant')
    search_fields = ('page', 'referrer', 'ip_hash')
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)
    readonly_fields = (
        'tenant', 'event_type', 'page', 'referrer', 'user_agent',
        'ip_hash', 'metadata', 'created_at', 'updated_at',
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
