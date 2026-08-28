from django.urls import path
from . import views

urlpatterns = [
    # Owner write (tenant_admin.js uses /api/blog/manage/ and /api/blog/manage/{id}/)
    # — these must come before the <slug:slug>/ catch-all below, otherwise
    # "manage" itself would be matched as a post slug.
    path('manage/',       views.BlogPostManageView.as_view(),       name='blog-manage'),
    path('manage/<uuid:pk>/', views.BlogPostManageDetailView.as_view(), name='blog-manage-detail'),
    # Public read
    path('',              views.BlogPostListView.as_view(),         name='blog-list'),
    path('tags/',         views.BlogTagListView.as_view(),          name='blog-tags'),
    path('<slug:slug>/',  views.BlogPostDetailView.as_view(),       name='blog-detail'),
]
