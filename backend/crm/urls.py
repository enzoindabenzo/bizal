from django.urls import path
from . import views

urlpatterns = [
    path('leads/', views.LeadListCreateView.as_view(), name='crm-leads'),
    path('leads/<uuid:pk>/', views.LeadDetailView.as_view(), name='crm-lead-detail'),
    path('leads/<uuid:lead_pk>/notes/', views.LeadNoteCreateView.as_view(), name='crm-lead-note'),
]
