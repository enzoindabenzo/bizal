from django.contrib import admin

from .models import Appointment, Service, ServiceProvider


@admin.register(ServiceProvider)
class ServiceProviderAdmin(admin.ModelAdmin):
    list_display = ('name', 'title', 'tenant', 'is_active')
    list_filter = ('is_active', 'tenant')
    search_fields = ('name', 'title', 'specialties')


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ('name', 'tenant', 'duration_minutes', 'price', 'is_active')
    list_filter = ('is_active', 'tenant')
    search_fields = ('name', 'description')
    filter_horizontal = ('providers',)


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = (
        'service', 'provider', 'guest_display', 'date', 'start_time', 'status', 'tenant',
    )
    list_filter = ('status', 'tenant', 'date')
    search_fields = ('guest_name', 'guest_email', 'guest_phone', 'user__email')
    date_hierarchy = 'date'
    raw_id_fields = ('user', 'tenant')

    @admin.display(description='Guest')
    def guest_display(self, obj):
        return obj.guest_name or (obj.user and obj.user.email) or '—'
