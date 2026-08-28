from django.contrib import admin
from django.utils import timezone

from .models import ContactMessage, PlatformInquiry


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'subject', 'tenant', 'is_read', 'created_at')
    list_filter = ('is_read', 'tenant')
    search_fields = ('name', 'email', 'subject', 'message')
    date_hierarchy = 'created_at'
    readonly_fields = ('ip_address', 'created_at', 'updated_at')
    actions = ['mark_as_read']

    @admin.action(description='Shëno si të lexuar')
    def mark_as_read(self, request, queryset):
        queryset.filter(is_read=False).update(is_read=True, replied_at=timezone.now())
        self.message_user(request, f"{queryset.count()} mesazhe u shënuan si të lexuara.")


@admin.register(PlatformInquiry)
class PlatformInquiryAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'subject', 'is_read', 'created_at')
    list_filter = ('is_read',)
    search_fields = ('name', 'email', 'subject', 'message')
    date_hierarchy = 'created_at'
    readonly_fields = ('ip_address', 'created_at', 'updated_at')
    actions = ['mark_as_read']

    @admin.action(description='Shëno si të lexuar')
    def mark_as_read(self, request, queryset):
        queryset.filter(is_read=False).update(is_read=True)
        self.message_user(request, f"{queryset.count()} kërkesa u shënuan si të lexuara.")
