from django.contrib import admin
from .models import Invoice, InvoiceLine, LoyaltyAccount, LoyaltyTransaction


class InvoiceLineInline(admin.TabularInline):
    model = InvoiceLine
    extra = 1
    readonly_fields = ('amount',)


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('invoice_number', 'customer_name', 'status', 'issued_date', 'due_date', 'tenant')
    list_filter = ('status', 'tenant')
    search_fields = ('invoice_number', 'customer_name', 'customer_email')
    inlines = [InvoiceLineInline]


class LoyaltyTransactionInline(admin.TabularInline):
    model = LoyaltyTransaction
    extra = 0
    readonly_fields = ('points', 'reason', 'source_type', 'source_id', 'created_at')
    can_delete = False
    ordering = ('-created_at',)


@admin.register(LoyaltyAccount)
class LoyaltyAccountAdmin(admin.ModelAdmin):
    list_display = ('user', 'tenant', 'points', 'lifetime_points')
    list_filter = ('tenant',)
    search_fields = ('user__email', 'user__full_name')
    inlines = [LoyaltyTransactionInline]
