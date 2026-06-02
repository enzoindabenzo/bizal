from rest_framework import serializers, generics
from rest_framework.permissions import AllowAny, IsAuthenticated
from tenants.permissions import IsTenantOwner
from .models import ServiceProvider, Service, Appointment


class ServiceProviderSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceProvider
        fields = ('id', 'name', 'title', 'bio', 'avatar', 'specialties')


class ServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Service
        fields = ('id', 'name', 'description', 'duration_minutes', 'price', 'is_active')


class AppointmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Appointment
        fields = ('id', 'service', 'provider', 'status', 'date', 'start_time', 'end_time',
                  'guest_name', 'guest_email', 'guest_phone', 'notes', 'created_at')
        read_only_fields = ('id', 'status', 'created_at')


class ProviderListView(generics.ListAPIView):
    serializer_class = ServiceProviderSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        return ServiceProvider.objects.filter(tenant=self.request.tenant, is_active=True)


class ServiceListView(generics.ListAPIView):
    serializer_class = ServiceSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        return Service.objects.filter(tenant=self.request.tenant, is_active=True)


class AppointmentCreateView(generics.CreateAPIView):
    serializer_class = AppointmentSerializer
    permission_classes = [AllowAny]

    def perform_create(self, serializer):
        user = self.request.user if self.request.user.is_authenticated else None
        serializer.save(tenant=self.request.tenant, user=user)


class AppointmentListView(generics.ListAPIView):
    serializer_class = AppointmentSerializer
    permission_classes = [IsTenantOwner]

    def get_queryset(self):
        return Appointment.objects.filter(tenant=self.request.tenant).select_related('service', 'provider')
