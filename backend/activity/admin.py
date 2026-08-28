from django.contrib import admin
from .models import ActivityLog


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'tenant', 'actor_name', 'verb', 'description')
    list_filter = ('verb', 'tenant')
    search_fields = ('description', 'actor_name', 'target_id')
    readonly_fields = (
        'tenant', 'actor', 'actor_name', 'verb', 'description',
        'target_type', 'target_id', 'metadata', 'created_at', 'updated_at',
    )
    ordering = ('-created_at',)
