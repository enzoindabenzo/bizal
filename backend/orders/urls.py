from django.urls import path
from . import views

urlpatterns = [
    path('',                        views.OrderListCreateView.as_view(), name='orders'),
    path('<uuid:pk>/',              views.OrderDetailView.as_view(),     name='order-detail'),
    path('<uuid:pk>/admin-update/', views.admin_update_order,            name='order-admin-update'),
]