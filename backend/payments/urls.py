from django.urls import path
from .views import (
    subscribe, customer_portal, stripe_webhook, PaymentListView, WebhookEventListView,
    create_booking_checkout, refund_booking_payment, available_pay_currencies,
)

urlpatterns = [
    path('',            PaymentListView.as_view(),  name='payment-list'),
    path('subscribe/',  subscribe,                  name='stripe-subscribe'),
    path('portal/',     customer_portal,            name='stripe-portal'),
    path('webhook/',    stripe_webhook,             name='stripe-webhook'),
    path('webhook-events/', WebhookEventListView.as_view(), name='webhook-events'),
    path('available-currencies/', available_pay_currencies, name='available-pay-currencies'),
    path('booking/<uuid:pk>/checkout/', create_booking_checkout, name='booking-checkout'),
    path('booking/<uuid:pk>/refund/',   refund_booking_payment,  name='booking-refund'),
]
