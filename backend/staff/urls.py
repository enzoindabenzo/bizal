from django.urls import path
from .views import StaffListCreateView, StaffDetailView, StaffScheduleListCreateView, StaffScheduleDetailView

urlpatterns = [
    path('',           StaffListCreateView.as_view(),  name='staff-list-create'),
    path('<uuid:pk>/', StaffDetailView.as_view(),       name='staff-detail'),
    # Schedule sub-resource
    path('<uuid:staff_pk>/schedules/',          StaffScheduleListCreateView.as_view(), name='staff-schedules'),
    path('<uuid:staff_pk>/schedules/<uuid:pk>/', StaffScheduleDetailView.as_view(),   name='staff-schedule-detail'),
]
