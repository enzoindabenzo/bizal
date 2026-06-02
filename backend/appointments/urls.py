from django.urls import path
from . import views

urlpatterns = [
    path('providers/', views.ProviderListView.as_view(), name='providers'),
    path('services/', views.ServiceListView.as_view(), name='services'),
    path('', views.AppointmentCreateView.as_view(), name='appointment-create'),
    path('admin/', views.AppointmentListView.as_view(), name='appointment-admin'),
]
