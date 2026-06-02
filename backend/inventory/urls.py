from django.urls import path
from . import views

urlpatterns = [
    path('', views.ProductListView.as_view(), name='products'),
    path('create/', views.ProductManageView.as_view(), name='product-create'),
    path('<uuid:pk>/', views.ProductDetailView.as_view(), name='product-detail'),
    path('<uuid:pk>/manage/', views.ProductUpdateView.as_view(), name='product-manage'),
]
