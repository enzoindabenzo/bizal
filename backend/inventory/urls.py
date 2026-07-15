from django.urls import path
from . import views
from .views import product_stock_adjust

urlpatterns = [
    path('categories/', views.ProductCategoryListView.as_view(), name='product-categories'),
    path('categories/<uuid:pk>/', views.ProductCategoryDetailView.as_view(), name='product-category-detail'),
    path('', views.ProductListView.as_view(), name='products'),
    path('create/', views.ProductManageView.as_view(), name='product-create'),
    path('<uuid:pk>/', views.ProductDetailView.as_view(), name='product-detail'),
    path('<uuid:pk>/manage/', views.ProductUpdateView.as_view(), name='product-manage'),
    path('<uuid:pk>/stock/',  product_stock_adjust,                name='product-stock-adjust'),
]
