from django.urls import path
from . import views

urlpatterns = [
    # Public
    path('pages/', views.StorefrontPageListView.as_view(), name='storefront-pages'),
    path('pages/<slug:slug>/', views.StorefrontPageDetailView.as_view(), name='storefront-page-detail'),
    path('hero/', views.HeroSlideListView.as_view(), name='hero-slides'),
    path('sections/', views.PageSectionPublicListView.as_view(), name='page-sections-public'),
    # Owner management
    path('manage/pages/', views.StorefrontPageManageView.as_view(), name='storefront-pages-manage'),
    path('manage/pages/<uuid:pk>/', views.StorefrontPageUpdateView.as_view(), name='storefront-page-update'),
    path('manage/hero/', views.HeroSlideManageView.as_view(), name='hero-manage'),
    path('manage/hero/<uuid:pk>/', views.HeroSlideUpdateView.as_view(), name='hero-update'),
    path('manage/sections/', views.PageSectionManageView.as_view(), name='page-sections-manage'),
    path('manage/sections/<uuid:pk>/', views.PageSectionUpdateView.as_view(), name='page-section-update'),
]
