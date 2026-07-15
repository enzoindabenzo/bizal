from django.urls import path
from .views import analytics_dashboard, track_event, export_bookings_csv, export_orders_csv, export_customers_csv

urlpatterns = [
    path('',       analytics_dashboard, name='analytics'),
    path('track/', track_event,         name='analytics-track'),
    path('export/bookings/',   export_bookings_csv,   name='analytics-export-bookings'),
    path('export/orders/',     export_orders_csv,     name='analytics-export-orders'),
    path('export/customers/',  export_customers_csv,  name='analytics-export-customers'),
]
