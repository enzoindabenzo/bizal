from rest_framework import serializers
from .models import CustomerSubscription


class CustomerSubscriptionSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(
        source='customer.display_name', read_only=True
    )

    class Meta:
        model = CustomerSubscription
        fields = (
            'id', 'customer', 'customer_name', 'name', 'description',
            'price', 'frequency', 'status', 'started_at',
            'next_billing_date', 'notes', 'created_at',
        )
        read_only_fields = ('created_at',)
