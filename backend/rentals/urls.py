from django.urls import path
from . import views

urlpatterns = [
    path('', views.RentalItemListView.as_view(), name='rentals'),
    path('featured/', views.RentalFeaturedListView.as_view(), name='rental-featured'),
    path('create/', views.RentalItemManageView.as_view(), name='rental-create'),
    path('<uuid:pk>/', views.RentalItemDetailView.as_view(), name='rental-detail'),
    path('<uuid:pk>/availability/', views.check_availability, name='rental-availability'),
    path('<uuid:pk>/booked-ranges/', views.booked_ranges, name='rental-booked-ranges'),
    path('<uuid:pk>/manage/', views.RentalItemUpdateView.as_view(), name='rental-manage'),
]
