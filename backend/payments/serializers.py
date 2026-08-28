from rest_framework import serializers
from .models import Payment


class PaymentSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.full_name', read_only=True, default='')

    class Meta:
        model = Payment
        fields = (
            'id', 'user', 'user_name', 'booking', 'amount', 'currency',
            'payment_type', 'status', 'description', 'metadata',
            'stripe_payment_intent', 'created_at',
        )
        read_only_fields = ('created_at',)
