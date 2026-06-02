from rest_framework import serializers, generics
from rest_framework.permissions import AllowAny
from tenants.permissions import IsTenantOwner
from .models import RoomType, Room


class RoomTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = RoomType
        fields = ('id', 'name', 'description', 'capacity', 'base_price', 'image', 'amenities')


class RoomSerializer(serializers.ModelSerializer):
    room_type_name = serializers.CharField(source='room_type.name', read_only=True)

    class Meta:
        model = Room
        fields = ('id', 'room_number', 'floor', 'status', 'room_type', 'room_type_name', 'notes')


class RoomTypeListView(generics.ListAPIView):
    serializer_class = RoomTypeSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        return RoomType.objects.filter(tenant=self.request.tenant)


class RoomListView(generics.ListAPIView):
    serializer_class = RoomSerializer
    permission_classes = [IsTenantOwner]

    def get_queryset(self):
        return Room.objects.filter(tenant=self.request.tenant).select_related('room_type')


class RoomTypeCreateUpdateView(generics.CreateAPIView):
    serializer_class = RoomTypeSerializer
    permission_classes = [IsTenantOwner]

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)
