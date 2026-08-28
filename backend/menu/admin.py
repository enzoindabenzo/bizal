from django.contrib import admin

from .models import MenuCategory, MenuItem


class MenuItemInline(admin.TabularInline):
    model = MenuItem
    extra = 0
    fields = ('name', 'price', 'is_available', 'is_featured', 'order')


@admin.register(MenuCategory)
class MenuCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'tenant', 'order', 'is_active')
    list_filter = ('is_active', 'tenant')
    search_fields = ('name',)
    inlines = [MenuItemInline]


@admin.register(MenuItem)
class MenuItemAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'tenant', 'price', 'is_available', 'is_featured', 'order')
    list_filter = ('is_available', 'is_featured', 'category', 'tenant')
    search_fields = ('name', 'description', 'allergens')
    list_editable = ('is_available', 'is_featured', 'order')
    raw_id_fields = ('category',)
