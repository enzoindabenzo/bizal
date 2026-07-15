from django.urls import path
from .views import (
    ReviewListCreateView, ReviewDeleteView,
    ReviewManageListView, ReviewModerateView,
)

urlpatterns = [
    path('', ReviewListCreateView.as_view(), name='reviews'),
    path('manage/', ReviewManageListView.as_view(), name='reviews-manage'),
    path('<uuid:pk>/', ReviewDeleteView.as_view(), name='review-detail'),
    path('<uuid:pk>/moderate/', ReviewModerateView.as_view(), name='review-moderate'),
]
