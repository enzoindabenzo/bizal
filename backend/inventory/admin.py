from django.contrib import admin

from .models import Product, ProductCategory


class ProductInline(admin.TabularInline):
    model = Product
    extra = 0
    fields = ('name', 'sku', 'price', 'stock', 'is_active', 'is_featured')


@admin.register(ProductCategory)
class ProductCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'tenant', 'slug')
    list_filter = ('tenant',)
    search_fields = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}
    inlines = [ProductInline]


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'tenant', 'price', 'stock', 'is_active', 'is_featured')
    list_filter = ('is_active', 'is_featured', 'category', 'tenant')
    search_fields = ('name', 'sku', 'barcode', 'description')
    list_editable = ('stock', 'is_active', 'is_featured')
    raw_id_fields = ('category',)
