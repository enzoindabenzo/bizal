from rest_framework import serializers
from .models import Payment


class PaymentSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.full_name', read_only=True, default='')

    class Meta:
        model = Payment
        fields = (
            'id', 'user', 'user_name', 'booking', 'invoice', 'order', 'amount', 'currency',
            'payment_type', 'payment_method', 'status', 'description', 'metadata',
            'stripe_payment_intent', 'recorded_by', 'created_at',
        )
        read_only_fields = ('created_at', 'recorded_by')


class ManualPaymentSerializer(serializers.ModelSerializer):
    """
    Used by RecordManualPaymentView for staff-recorded cash/bank_transfer
    payments. Deliberately separate from PaymentSerializer (which backs the
    read-only PaymentListView) so the writable surface here is narrow and
    explicit — staff can only ever create 'cash' or 'bank_transfer' rows
    through this endpoint, never 'stripe' (those only ever come from the
    webhook) and never arbitrary status/metadata.
    """
    payment_method = serializers.ChoiceField(choices=[('cash', 'Cash'), ('bank_transfer', 'Bank Transfer')])

    class Meta:
        model = Payment
        fields = (
            'id', 'booking', 'invoice', 'order', 'amount', 'currency',
            'payment_type', 'payment_method', 'description', 'created_at',
        )
        read_only_fields = ('created_at',)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Scope booking/invoice/order FKs to the current tenant, matching the
        # same IDOR-prevention pattern InvoiceSerializer uses for 'customer'
        # — otherwise a staff member could record a payment against another
        # tenant's booking/invoice/order by guessing its UUID.
        request = self.context.get('request')
        if request and hasattr(request, 'tenant') and request.tenant:
            from bookings.models import Booking
            from billing.models import Invoice
            from orders.models import Order
            self.fields['booking'].queryset = Booking.objects.filter(tenant=request.tenant)
            self.fields['invoice'].queryset = Invoice.objects.filter(tenant=request.tenant)
            self.fields['order'].queryset = Order.objects.filter(tenant=request.tenant)

    def validate(self, attrs):
        payment_type = attrs.get('payment_type')
        if payment_type == 'invoice' and not attrs.get('invoice'):
            raise serializers.ValidationError({'invoice': 'Required when payment_type is "invoice".'})
        if payment_type == 'booking_deposit' and not attrs.get('booking'):
            raise serializers.ValidationError({'booking': 'Required when payment_type is "booking_deposit".'})
        if payment_type == 'order' and not attrs.get('order'):
            raise serializers.ValidationError({'order': 'Required when payment_type is "order".'})
        return attrs