from django.contrib import admin
from .models import StorefrontPage, HeroSlide, PageSection


@admin.register(StorefrontPage)
class StorefrontPageAdmin(admin.ModelAdmin):
    list_display = ('title', 'slug', 'is_published', 'tenant')
    list_filter = ('is_published', 'tenant')
    prepopulated_fields = {'slug': ('title',)}


@admin.register(HeroSlide)
class HeroSlideAdmin(admin.ModelAdmin):
    list_display = ('title', 'order', 'is_active', 'tenant')
    list_filter = ('is_active', 'tenant')


@admin.register(PageSection)
class PageSectionAdmin(admin.ModelAdmin):
    list_display = ('page_key', 'lock_key', 'section_type', 'title', 'hidden', 'order', 'tenant')
    list_filter = ('page_key', 'section_type', 'hidden', 'tenant')
