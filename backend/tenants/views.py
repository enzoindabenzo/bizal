from django.core.cache import cache
from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAdminUser
from rest_framework.response import Response

from .models import Tenant
from .serializers import (
    TenantPublicSerializer, TenantSettingsSerializer,
    TenantAdminSerializer, TenantSignupSerializer,
)
from .permissions import IsTenantOwner, MainDomainOnly
from accounts.models import User


class TenantInfoView(generics.RetrieveAPIView):
    serializer_class = TenantPublicSerializer
    permission_classes = [AllowAny]

    def get_object(self):
        return self.request.tenant

    def retrieve(self, request, *args, **kwargs):
        if not request.tenant:
            return Response({'detail': 'Main domain — no tenant.'}, status=404)
        return super().retrieve(request, *args, **kwargs)


class TenantSettingsView(generics.RetrieveUpdateAPIView):
    serializer_class = TenantSettingsSerializer
    permission_classes = [IsTenantOwner]

    def get_object(self):
        return self.request.tenant

    def perform_update(self, serializer):
        serializer.save()
        cache.delete(f'tenant:{self.request.tenant.slug}')


@api_view(['POST'])
@permission_classes([AllowAny, MainDomainOnly])
def tenant_signup(request):
    serializer = TenantSignupSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    d = serializer.validated_data

    tenant = Tenant.objects.create(
        name=d['business_name'],
        slug=d['slug'],
        business_type=d['business_type'],
        is_active=False,
        plan='starter',
    )

    user = User.objects.create_user(
        email=d['owner_email'],
        password=d['owner_password'],
        full_name=d['owner_name'],
        tenant=tenant,
        role='owner',
    )

    return Response({
        'message': 'Tenant created. Awaiting activation.',
        'slug': tenant.slug,
        'user_id': str(user.id),
    }, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([AllowAny])
def check_slug(request):
    slug = request.query_params.get('slug', '')
    available = not Tenant.objects.filter(slug=slug).exists()
    return Response({'slug': slug, 'available': available})


class SuperadminTenantListView(generics.ListCreateAPIView):
    queryset = Tenant.objects.all().order_by('-created_at')
    serializer_class = TenantAdminSerializer
    permission_classes = [IsAdminUser]


class SuperadminTenantDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Tenant.objects.all()
    serializer_class = TenantAdminSerializer
    permission_classes = [IsAdminUser]

    def perform_update(self, serializer):
        instance = serializer.save()
        cache.delete(f'tenant:{instance.slug}')
