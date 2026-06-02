from django.urls import path
from .views import analytics_dashboard

urlpatterns = [
    path('', analytics_dashboard, name='analytics'),
]
