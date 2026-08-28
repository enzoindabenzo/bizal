from django.contrib import admin

from .models import Booking


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = (
        'booking_type', 'resource_label', 'guest_display', 'status',
        'start_date', 'total_price', 'tenant',
    )
    list_filter = ('booking_type', 'status', 'tenant')
    search_fields = ('guest_name', 'guest_email', 'guest_phone', 'stripe_session_id', 'resource_label')
    date_hierarchy = 'created_at'
    raw_id_fields = ('user', 'tenant')

    @admin.display(description='Guest')
    def guest_display(self, obj):
        return obj.guest_name or (obj.user and obj.user.email) or '—'
