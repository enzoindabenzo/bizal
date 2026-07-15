from django.urls import path
from . import views

urlpatterns = [
    # Public
    path('providers/',                        views.ProviderListView.as_view(),       name='providers'),
    path('services/',                         views.ServiceListView.as_view(),        name='services'),
    path('',                                  views.AppointmentCreateView.as_view(),  name='appointment-create'),
    # Staff / Owner
    path('admin/',                            views.AppointmentListView.as_view(),    name='appointment-list'),
    path('<uuid:pk>/cancel/',                 views.cancel_appointment,               name='appointment-cancel'),
    path('<uuid:pk>/status/',                 views.update_appointment_status,        name='appointment-status'),
    # Owner management — canonical paths
    path('manage/services/',                  views.ServiceManageView.as_view(),      name='service-manage'),
    path('manage/services/<uuid:pk>/',        views.ServiceDetailView.as_view(),      name='service-detail'),
    path('manage/providers/',                 views.ProviderManageView.as_view(),     name='provider-manage'),
    path('manage/providers/<uuid:pk>/',       views.ProviderDetailView.as_view(),     name='provider-detail'),
    # Alias paths matching tenant_admin.js calls
    path('services/<uuid:pk>/',              views.ServiceDetailView.as_view(),       name='service-detail-alias'),
    path('providers/<uuid:pk>/',             views.ProviderDetailView.as_view(),      name='provider-detail-alias'),
]
