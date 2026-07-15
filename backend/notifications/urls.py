from django.urls import path
from . import views

urlpatterns = [
    path('', views.NotificationListView.as_view(), name='notifications'),
    path('unread-count/', views.unread_count, name='notifications-unread-count'),
    path('mark-all-read/', views.mark_all_read, name='notifications-mark-all'),
    path('<uuid:pk>/read/', views.mark_read, name='notification-read'),
]
