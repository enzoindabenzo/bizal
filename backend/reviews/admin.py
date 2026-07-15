from django.contrib import admin
from django.utils import timezone

from .models import Review
from .platform_models import PlatformReview


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    """
    Per-tenant product/service/business reviews (the "vlerësimet" table shown
    inside each tenant's admin panel). Previously unregistered here — only
    the separate platform-wide PlatformReview below was in Django admin.
    """
    list_display  = ['user', 'tenant', 'review_type', 'rating', 'object_label', 'is_approved', 'created_at']
    list_filter   = ['is_approved', 'rating', 'review_type', 'tenant']
    list_editable = ['is_approved']
    search_fields = ['user__email', 'user__full_name', 'comment', 'object_label']
    raw_id_fields = ['user', 'tenant']
    actions       = ['approve_reviews']

    @admin.action(description='✓ Aprovo vlerësimet e zgjedhura')
    def approve_reviews(self, request, queryset):
        queryset.update(is_approved=True)
        self.message_user(request, f"{queryset.count()} vlerësime u aprovuan.")


@admin.register(PlatformReview)
class PlatformReviewAdmin(admin.ModelAdmin):
    list_display  = ['reviewer_name', 'business_name', 'rating', 'is_approved', 'created_at']
    list_filter   = ['is_approved', 'rating']
    list_editable = ['is_approved']
    search_fields = ['reviewer_name', 'business_name', 'comment']
    actions       = ['approve_reviews']

    @admin.action(description='✓ Aprovo vlerësimet e zgjedhura')
    def approve_reviews(self, request, queryset):
        queryset.update(is_approved=True, approved_at=timezone.now())
        self.message_user(request, f"{queryset.count()} vlerësime u aprovuan.")