from django.urls import path
from .platform_views import (
    PlatformReviewListCreateView,
    PlatformReviewSummaryView,
    PlatformReviewAdminView,
    PlatformReviewApproveView,
)

urlpatterns = [
    path('',              PlatformReviewListCreateView.as_view(), name='platform-reviews'),
    path('summary/',      PlatformReviewSummaryView.as_view(),    name='platform-reviews-summary'),
    path('admin/',        PlatformReviewAdminView.as_view(),      name='platform-reviews-admin'),
    path('admin/<uuid:pk>/', PlatformReviewApproveView.as_view(), name='platform-reviews-approve'),
]
