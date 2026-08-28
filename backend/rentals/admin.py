from django.contrib import admin
from .models import RentalItem


@admin.register(RentalItem)
class RentalItemAdmin(admin.ModelAdmin):
    list_display = ('name', 'tenant', 'rental_type', 'price_per_day', 'status', 'is_featured')
    list_filter = ('tenant', 'rental_type', 'status', 'is_featured')
    search_fields = ('name', 'tenant__name', 'city')
    list_editable = ('status', 'is_featured')
    readonly_fields = ('id',)
    fieldsets = (
        (None, {
            'fields': ('id', 'tenant', 'name', 'rental_type', 'description')
        }),
        ('Pricing', {
            'fields': ('price_per_day', 'deposit')
        }),
        ('Details', {
            'fields': ('status', 'city', 'image', 'specs', 'is_featured')
        }),
    )
