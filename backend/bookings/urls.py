from django.urls import path
from . import views

urlpatterns = [
    path('', views.BookingListCreateView.as_view(), name='bookings'),
    path('<uuid:pk>/', views.BookingDetailView.as_view(), name='booking-detail'),
    path('<uuid:pk>/cancel/', views.cancel_booking, name='booking-cancel'),
    path('<uuid:pk>/admin-update/', views.admin_update_booking, name='booking-admin-update'),
]
