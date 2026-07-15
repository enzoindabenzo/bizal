from rest_framework import generics
from tenants.permissions import HasTenantRole, TenantDomainOnly
from rest_framework.permissions import IsAuthenticated
from .models import CustomerSubscription
from .serializers import CustomerSubscriptionSerializer


class SubscriptionListCreateView(generics.ListCreateAPIView):
    serializer_class = CustomerSubscriptionSerializer
    permission_classes = [HasTenantRole('accountant')]

    def get_queryset(self):
        qs = CustomerSubscription.objects.filter(
            tenant=self.request.tenant
        ).select_related('customer')
        sub_status = self.request.query_params.get('status')
        if sub_status:
            qs = qs.filter(status=sub_status)
        customer_id = self.request.query_params.get('customer')
        if customer_id:
            qs = qs.filter(customer_id=customer_id)
        return qs

    def perform_create(self, serializer):
        # Validate that the customer being assigned belongs to this tenant.
        # Without this check, an accountant could pass any User UUID as
        # 'customer' (DRF's default PrimaryKeyRelatedField queries all users),
        # silently assigning a customer from a different tenant and corrupting
        # cross-tenant data visibility in MySubscriptionsView.
        customer = serializer.validated_data.get('customer')
        if customer and getattr(customer, 'tenant_id', None) != self.request.tenant.pk:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({'customer': 'Customer does not belong to this tenant.'})
        serializer.save(tenant=self.request.tenant)


class SubscriptionDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = CustomerSubscriptionSerializer
    permission_classes = [HasTenantRole('accountant')]

    def get_queryset(self):
        return CustomerSubscription.objects.filter(tenant=self.request.tenant)

    def perform_update(self, serializer):
        # Guard customer reassignment on PATCH/PUT same as on create.
        customer = serializer.validated_data.get('customer')
        if customer and getattr(customer, 'tenant_id', None) != self.request.tenant.pk:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({'customer': 'Customer does not belong to this tenant.'})
        serializer.save()


class MySubscriptionsView(generics.ListAPIView):
    """A customer sees their own subscriptions.

    M-2 FIX: Added TenantDomainOnly to permission_classes. Previously, a
    request to this endpoint from the main domain (where request.tenant is None)
    would silently return HTTP 200 [] because filter(tenant=None) generates
    WHERE tenant_id IS NULL, returning an empty queryset. This is consistent with
    every other tenant-scoped endpoint which either uses TenantDomainOnly or an
    equivalent explicit guard. The 400 response from TenantDomainOnly is the
    correct, predictable contract for main-domain callers.
    """
    serializer_class = CustomerSubscriptionSerializer
    permission_classes = [IsAuthenticated, TenantDomainOnly]

    def get_queryset(self):
        return CustomerSubscription.objects.filter(
            tenant=self.request.tenant,
            customer=self.request.user,
        )
