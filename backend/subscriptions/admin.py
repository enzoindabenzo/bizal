from django.contrib import admin
from .models import CustomerSubscription


@admin.register(CustomerSubscription)
class CustomerSubscriptionAdmin(admin.ModelAdmin):
    list_display = ('customer', 'name', 'frequency', 'price', 'status', 'next_billing_date', 'tenant')
    list_filter = ('status', 'frequency', 'tenant')
    search_fields = ('customer__email', 'name')
