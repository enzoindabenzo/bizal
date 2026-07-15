from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    """
    Read-only browser for user notifications. These are created by
    notifications.utils.notify_owner()/notify_owner_async() from other
    apps' business logic, not by hand — editing/adding is disabled here,
    same pattern as analytics.AnalyticsEvent and payments.WebhookEvent.
    """
    list_display = ('title', 'notification_type', 'user', 'tenant', 'is_read', 'created_at')
    list_filter = ('notification_type', 'is_read', 'tenant')
    search_fields = ('title', 'body', 'user__email', 'idempotency_key')
    date_hierarchy = 'created_at'
    raw_id_fields = ('user', 'tenant')
    readonly_fields = (
        'tenant', 'user', 'notification_type', 'title', 'body',
        'metadata', 'idempotency_key', 'created_at', 'updated_at',
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
