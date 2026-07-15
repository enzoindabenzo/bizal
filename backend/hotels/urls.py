from django.urls import path
from . import views

urlpatterns = [
    path('room-types/', views.RoomTypeListView.as_view(), name='room-types'),
    path('room-types/create/', views.RoomTypeCreateUpdateView.as_view(), name='room-type-create'),
    path('room-types/<uuid:pk>/', views.RoomTypeDetailView.as_view(), name='room-type-detail'),
    path('room-types/<uuid:pk>/rooms/', views.RoomsByTypeView.as_view(), name='room-type-rooms'),
    path('room-types/<uuid:pk>/seasonal-prices/', views.SeasonalPriceView.as_view(), name='seasonal-prices'),
    path('room-types/<uuid:pk>/booked-ranges/', views.room_type_booked_ranges, name='room-type-booked-ranges'),
    path('rooms/', views.RoomListView.as_view(), name='rooms'),
    path('rooms/calendar/', views.rooms_calendar, name='rooms-calendar'),
    path('rooms/<uuid:pk>/', views.RoomDetailView.as_view(), name='room-detail'),
    path('find-available-room/', views.find_available_room, name='find-available-room'),
    # RoomBooking — list/create bookings and manage individual ones
    path('bookings/', views.RoomBookingListCreateView.as_view(), name='room-bookings'),
    path('bookings/<int:pk>/', views.RoomBookingDetailView.as_view(), name='room-booking-detail'),
]
