from django.urls import path
from . import views

urlpatterns = [
    path('', views.SubscriptionListCreateView.as_view(), name='subscriptions'),
    path('<uuid:pk>/', views.SubscriptionDetailView.as_view(), name='subscription-detail'),
    path('mine/', views.MySubscriptionsView.as_view(), name='my-subscriptions'),
]
