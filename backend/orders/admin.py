from django.contrib import admin
from .models import Order, OrderItem


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    raw_id_fields = ('menu_item',)


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'tenant', 'status', 'order_type', 'total_price', 'created_at')
    list_filter = ('status', 'order_type', 'tenant')
    raw_id_fields = ('user', 'tenant')
    inlines = [OrderItemInline]
