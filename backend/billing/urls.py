from django.urls import path
from . import views

urlpatterns = [
    path('loyalty/me/',                            views.LoyaltyMeView.as_view(),          name='loyalty-me'),
    path('invoices/',                              views.InvoiceListCreateView.as_view(),  name='invoices'),
    path('invoices/<uuid:pk>/',                    views.InvoiceDetailView.as_view(),      name='invoice-detail'),
    path('invoices/<uuid:pk>/pdf/',                views.invoice_pdf,                      name='invoice-pdf'),
    path('invoices/<uuid:invoice_pk>/lines/',      views.InvoiceLineCreateView.as_view(),  name='invoice-lines'),
]
