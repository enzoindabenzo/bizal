from django.urls import path
from . import views

urlpatterns = [
    path('', views.ContactSubmitView.as_view(), name='contact-submit'),
    path('admin/messages/', views.ContactMessageListView.as_view(), name='contact-messages'),
    path('admin/messages/<uuid:pk>/', views.ContactMessageDetailView.as_view(), name='contact-message-detail'),
    path('admin/messages/<uuid:pk>/reply/', views.ContactReplyView.as_view(), name='contact-reply'),
]
