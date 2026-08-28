from django.contrib import admin
from .models import Lead, LeadNote


class LeadNoteInline(admin.TabularInline):
    model = LeadNote
    extra = 0
    readonly_fields = ('created_at',)


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'status', 'source', 'assigned_to', 'tenant')
    list_filter = ('status', 'source', 'tenant')
    search_fields = ('name', 'email', 'phone')
    inlines = [LeadNoteInline]
