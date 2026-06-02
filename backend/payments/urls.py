from django.urls import path
from . import views

urlpatterns = [
    path('subscribe/', views.subscribe, name='subscribe'),
    path('webhook/', views.stripe_webhook, name='stripe-webhook'),
]
