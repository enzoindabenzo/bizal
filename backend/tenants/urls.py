from django.urls import path
from . import views

urlpatterns = [
    path('info/', views.TenantInfoView.as_view(), name='tenant-info'),
    path('settings/', views.TenantSettingsView.as_view(), name='tenant-settings'),
    path('signup/', views.tenant_signup, name='tenant-signup'),
    path('check-slug/', views.check_slug, name='check-slug'),
    path('superadmin/tenants/', views.SuperadminTenantListView.as_view(), name='superadmin-tenants'),
    path('superadmin/tenants/<uuid:pk>/', views.SuperadminTenantDetailView.as_view(), name='superadmin-tenant-detail'),
]
