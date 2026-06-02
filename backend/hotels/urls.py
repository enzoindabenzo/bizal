from django.urls import path
from . import views

urlpatterns = [
    path('room-types/', views.RoomTypeListView.as_view(), name='room-types'),
    path('room-types/create/', views.RoomTypeCreateUpdateView.as_view(), name='room-type-create'),
    path('rooms/', views.RoomListView.as_view(), name='rooms'),
]
