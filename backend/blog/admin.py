from django.contrib import admin
from .models import BlogPost, BlogTag


@admin.register(BlogTag)
class BlogTagAdmin(admin.ModelAdmin):
    list_display = ('name', 'tenant', 'slug')
    list_filter = ('tenant',)
    prepopulated_fields = {'slug': ('name',)}


@admin.register(BlogPost)
class BlogPostAdmin(admin.ModelAdmin):
    list_display = ('title', 'tenant', 'status', 'published_at', 'view_count')
    list_filter = ('tenant', 'status')
    prepopulated_fields = {'slug': ('title',)}
    raw_id_fields = ('author',)