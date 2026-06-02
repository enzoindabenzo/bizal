from django.urls import path
from . import views

urlpatterns = [
    path('', views.MenuListView.as_view(), name='menu'),
    path('items/', views.MenuItemCreateView.as_view(), name='menu-item-create'),
    path('items/<uuid:pk>/', views.MenuItemUpdateView.as_view(), name='menu-item-detail'),
]
