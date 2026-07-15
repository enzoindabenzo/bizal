import json

from django.contrib import admin
from django.utils.html import format_html

from .models import WebhookEvent


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    """
    Read-only browser for the Stripe webhook audit log. Mirrors
    WebhookEventListView (the JS superadmin panel's data source) so both
    surfaces read the same table — this just adds a native Django-admin view
    of it, with no separate serializer or endpoint to keep in sync.
    """
    list_display  = ('event_type', 'status_badge', 'stripe_event_id', 'created_at')
    list_filter   = ('status', 'event_type')
    search_fields = ('stripe_event_id', 'event_type', 'error_message')
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)
    readonly_fields = ('stripe_event_id', 'event_type', 'status', 'pretty_payload',
                       'error_message', 'created_at')
    fields = ('stripe_event_id', 'event_type', 'status', 'error_message',
              'pretty_payload', 'created_at')

    # It's an immutable audit log: no creating or editing rows by hand.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def status_badge(self, obj):
        colors = {'processed': '#1A6B42', 'ignored': '#7A4010', 'failed': '#8B1A1A'}
        return format_html(
            '<span style="color:{};font-weight:600;">{}</span>',
            colors.get(obj.status, '#5F5B53'), obj.get_status_display(),
        )
    status_badge.short_description = 'Status'

    def pretty_payload(self, obj):
        return format_html('<pre style="white-space:pre-wrap;margin:0;">{}</pre>',
                            json.dumps(obj.payload, indent=2, ensure_ascii=False))
    pretty_payload.short_description = 'Payload'
