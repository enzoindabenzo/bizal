from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from . import views

urlpatterns = [
    path('register/',               views.RegisterView.as_view(),               name='register'),
    path('login/',                  views.CustomTokenObtainPairView.as_view(),   name='login'),
    path('token/refresh/',          TokenRefreshView.as_view(),                 name='token-refresh'),
    path('logout/',                 views.LogoutView.as_view(),                 name='logout'),
    path('me/',                     views.MeView.as_view(),                     name='me'),
    path('me/bookings/',            views.MeBookingsView.as_view(),             name='me-bookings'),
    path('me/orders/',              views.MeOrdersView.as_view(),               name='me-orders'),
    path('me/appointments/',       views.MeAppointmentsView.as_view(),          name='me-appointments'),
    path('me/notifications/',      views.MeNotificationPrefsView.as_view(),     name='me-notifications'),
    path('me/reviews/',             views.MeReviewsView.as_view(),              name='me-reviews'),
    path('me/delete/',              views.MeDeleteView.as_view(),               name='me-delete'),
    path('verify-email/',                views.EmailVerificationSendView.as_view(),    name='verify-email-send'),
    path('verify-email/<uid>/<token>/',   views.EmailVerificationConfirmView.as_view(), name='verify-email-confirm'),
    path('change-password/',        views.ChangePasswordView.as_view(),         name='change-password'),
    path('password-reset/',         views.PasswordResetRequestView.as_view(),   name='password-reset'),
    path('password-reset/confirm/', views.PasswordResetConfirmView.as_view(),   name='password-reset-confirm'),
]