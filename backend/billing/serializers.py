from rest_framework import serializers
from .models import Invoice, InvoiceLine, LoyaltyAccount, LoyaltyTransaction, POINT_VALUE_IN_EUR


class InvoiceLineSerializer(serializers.ModelSerializer):
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = InvoiceLine
        fields = ('id', 'description', 'quantity', 'unit_price', 'amount')


class InvoiceSerializer(serializers.ModelSerializer):
    lines = InvoiceLineSerializer(many=True, read_only=True)
    # 'total' is the read-only computed property on the model.
    # 'total_amount' is the actual DB field; expose it so any client POSTing
    # or PATCHing with 'total_amount' is not silently ignored.
    total = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    total_amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = Invoice
        fields = (
            'id', 'customer', 'customer_name', 'customer_email',
            'invoice_number', 'status', 'issued_date', 'due_date',
            'notes', 'lines', 'total', 'total_amount', 'created_at',
        )
        read_only_fields = ('created_at', 'total', 'total_amount')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Scope the customer FK to the current tenant so an accountant
        # cannot reference a User from a different tenant by guessing their
        # UUID. DRF's default PrimaryKeyRelatedField queries ALL users; this
        # restricts it to users whose tenant FK matches the request tenant.
        request = self.context.get('request')
        if request and hasattr(request, 'tenant') and request.tenant:
            from accounts.models import User
            self.fields['customer'].queryset = User.objects.filter(
                tenant=request.tenant
            )


class LoyaltyTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = LoyaltyTransaction
        fields = ('id', 'points', 'reason', 'source_type', 'created_at')


class LoyaltyAccountSerializer(serializers.ModelSerializer):
    history = serializers.SerializerMethodField()
    point_value = serializers.SerializerMethodField()

    class Meta:
        model = LoyaltyAccount
        fields = ('points', 'lifetime_points', 'point_value', 'history')

    def get_point_value(self, obj):
        return POINT_VALUE_IN_EUR

    DEFAULT_HISTORY_PAGE_SIZE = 50

    def get_history(self, obj):
        # Most-recent-first. Capped via a configurable page size rather than
        # a hard-coded slice so callers can pass ?history_limit=N to the
        # LoyaltyAccountView without a serializer change.
        request = self.context.get('request')
        try:
            limit = int(request.query_params.get('history_limit', self.DEFAULT_HISTORY_PAGE_SIZE))
            limit = min(max(limit, 1), 200)  # clamp to [1, 200]
        except (AttributeError, ValueError, TypeError):
            limit = self.DEFAULT_HISTORY_PAGE_SIZE
        qs = obj.transactions.order_by('-created_at')[:limit]
        return LoyaltyTransactionSerializer(qs, many=True).data
