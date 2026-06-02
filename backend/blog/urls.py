from django.urls import path
from . import views

urlpatterns = [
    path('', views.BlogPostListView.as_view(), name='blog-list'),
    path('tags/', views.BlogTagListView.as_view(), name='blog-tags'),
    path('<slug:slug>/', views.BlogPostDetailView.as_view(), name='blog-detail'),
]
