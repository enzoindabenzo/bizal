from django.utils.decorators import method_decorator
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.tokens import RefreshToken
from django.conf import settings as django_settings

from .models import User
from .serializers import RegisterSerializer, UserProfileSerializer, CustomTokenObtainPairSerializer

# ---- Rate limiting: only active when RATELIMIT_ENABLE is True (production) ----
def _ratelimit_decorator(rate):
    """Returns a real ratelimit decorator in production, a no-op in local dev."""
    if getattr(django_settings, 'RATELIMIT_ENABLE', True):
        from django_ratelimit.decorators import ratelimit
        return ratelimit(key='ip', rate=rate, method='POST', block=True)
    # Local dev: no-op decorator
    return lambda f: f


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]

    @method_decorator(_ratelimit_decorator('5/m'))
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)

    def perform_create(self, serializer):
        tenant = self.request.tenant
        serializer.save(tenant=tenant, role='customer')


class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer

    @method_decorator(_ratelimit_decorator('5/m'))
    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code == 200:
            try:
                user = User.objects.get(email=request.data.get('email'))
            except User.DoesNotExist:
                return response
            # Reject main-domain login for non-staff
            if request.tenant is None and not user.is_staff:
                return Response(
                    {'detail': 'Staff login only on main domain.'},
                    status=status.HTTP_403_FORBIDDEN
                )
            # Reject cross-tenant login
            if request.tenant and user.tenant and user.tenant != request.tenant:
                return Response(
                    {'detail': 'Invalid credentials for this portal.'},
                    status=status.HTTP_403_FORBIDDEN
                )
        return response


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            refresh_token = request.data['refresh']
            token = RefreshToken(refresh_token)
            token.blacklist()
            return Response({'detail': 'Logged out.'}, status=status.HTTP_200_OK)
        except Exception:
            return Response({'detail': 'Invalid token.'}, status=status.HTTP_400_BAD_REQUEST)


class MeView(generics.RetrieveUpdateAPIView):
    serializer_class = UserProfileSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user
