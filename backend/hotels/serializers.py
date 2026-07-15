from rest_framework import serializers
from .models import RoomType, Room, SeasonalPrice


class SeasonalPriceSerializer(serializers.ModelSerializer):
    class Meta:
        model = SeasonalPrice
        fields = ('id', 'name', 'start_date', 'end_date', 'price')


class RoomTypeSerializer(serializers.ModelSerializer):
    seasonal_prices = SeasonalPriceSerializer(many=True, read_only=True)

    class Meta:
        model = RoomType
        fields = ('id', 'name', 'description', 'capacity', 'base_price', 'image', 'amenities', 'seasonal_prices')


class RoomSerializer(serializers.ModelSerializer):
    room_type_name = serializers.CharField(source='room_type.name', read_only=True)
    # room_type is set from the URL kwarg in perform_create (RoomsByTypeView) and
    # is never updated after creation — clients send room_number/floor/status/notes only.
    room_type = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Room
        fields = ('id', 'room_number', 'floor', 'status', 'room_type', 'room_type_name', 'notes')
