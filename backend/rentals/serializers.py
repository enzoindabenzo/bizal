from rest_framework import serializers
from .models import RentalItem


class RentalItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = RentalItem
        fields = ('id', 'name', 'rental_type', 'description', 'price_per_day',
                  'deposit', 'status', 'image', 'city', 'specs', 'is_featured')
