from django.urls import path

from .views import SusConfigView, UsabilitySurveyResponseCreateView

urlpatterns = [
    path('sus/', UsabilitySurveyResponseCreateView.as_view(), name='research-sus-submit'),
    path('sus/config/', SusConfigView.as_view(), name='research-sus-config'),
]
