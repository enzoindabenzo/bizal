from rest_framework import serializers
from .models import Booking


class BookingSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = (
            'id', 'booking_type', 'status', 'start_date', 'end_date',
            'start_time', 'end_time', 'resource_label',
            'guest_name', 'guest_email', 'guest_phone', 'guest_count',
            'total_price', 'deposit_paid', 'notes', 'user_name', 'created_at',
        )
        read_only_fields = ('id', 'status', 'deposit_paid', 'user_name', 'created_at')

    def get_user_name(self, obj):
        return obj.user.display_name if obj.user else obj.guest_name
