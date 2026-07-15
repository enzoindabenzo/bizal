from rest_framework import generics, serializers
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from tenants.permissions import TenantDomainOnly, IsTenantOwner, HasTenantFeature
from bizal.throttles import PublicReadThrottle
from .models import Review
from .serializers import ReviewSerializer


class ReviewListCreateView(generics.ListCreateAPIView):
    serializer_class = ReviewSerializer

    def get_permissions(self):
        if self.request.method == 'GET':
            return [AllowAny()]
        return [IsAuthenticated(), TenantDomainOnly()]

    def get_throttles(self):
        if self.request.method == 'GET':
            return [PublicReadThrottle()]
        return super().get_throttles()

    def get_queryset(self):
        return Review.objects.filter(tenant=self.request.tenant, is_approved=True).select_related('user')

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        limit = request.query_params.get('limit')
        if limit:
            try:
                # H-1 FIX: Cap at MAX_PAGE_SIZE (100) to prevent unauthenticated
                # callers from issuing ?limit=999999 and forcing a full table scan
                # into memory, bypassing the paginator's guard entirely.
                capped = min(int(limit), 100)
                queryset = queryset[:capped]
                serializer = self.get_serializer(queryset, many=True)
                return Response(serializer.data)
            except (ValueError, AssertionError):
                pass
        page = self.paginate_queryset(queryset)
        if page is not None:
            return self.get_paginated_response(self.get_serializer(page, many=True).data)
        return Response(self.get_serializer(queryset, many=True).data)

    def perform_create(self, serializer):
        # HIGH-1 FIX: Guard against cross-tenant review injection.
        # IsAuthenticated verifies the JWT but does NOT verify that the
        # authenticated user belongs to request.tenant. A customer registered
        # under Tenant A could POST a review to Tenant B's subdomain and have
        # it stored with their user_id against Tenant B.
        # Guest users (user.tenant_id is None) are still allowed through — they
        # have no home tenant and can legitimately review any business.
        user = self.request.user
        if user.tenant_id and user.tenant_id != self.request.tenant.pk:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('You cannot review a business you are not registered with.')
        # is_approved defaults to False at the model level — new reviews
        # sit in a moderation queue (see ReviewManageListView /
        # ReviewModerateView below) until the tenant owner approves them.
        serializer.save(
            tenant=self.request.tenant,
            user=user,
            is_approved=False,
        )


class ReviewDeleteView(generics.DestroyAPIView):
    """Tenant owner can delete any review on their tenant."""
    serializer_class = ReviewSerializer
    # HasTenantFeature('reviews') added: ReviewManageListView and
    # ReviewModerateView both already gate on this feature, but delete
    # previously didn't — an owner on a plan without the 'reviews' feature
    # could still DELETE reviews even though they couldn't list or
    # moderate them.
    permission_classes = [IsAuthenticated, TenantDomainOnly, HasTenantFeature('reviews')]

    def get_queryset(self):
        # owners/managers can delete any review; customers can only delete their own.
        # HIGH-1 FIX: add tenant membership check for the owner/manager branch so a
        # user who is an owner on Tenant A cannot DELETE reviews on Tenant B by sending
        # their JWT to Tenant B's subdomain. Superusers bypass this check intentionally.
        user = self.request.user
        qs = Review.objects.filter(tenant=self.request.tenant).select_related('user')
        is_own_tenant_staff = (
            user.is_superuser or
            (user.role in ('owner', 'manager') and getattr(user, 'tenant_id', None) == self.request.tenant.pk)
        )
        if is_own_tenant_staff:
            return qs
        return qs.filter(user=user)


class ReviewManageListView(generics.ListAPIView):
    """
    Owner-only: list ALL reviews for the tenant (approved and pending),
    so the moderation queue is visible. ?status=pending filters to only
    unapproved reviews. Requires the 'reviews' feature on the tenant's plan.
    """
    serializer_class = ReviewSerializer
    permission_classes = [IsTenantOwner, HasTenantFeature('reviews')]

    def get_queryset(self):
        qs = Review.objects.filter(tenant=self.request.tenant).select_related('user')
        status_filter = self.request.query_params.get('status')
        if status_filter == 'pending':
            qs = qs.filter(is_approved=False)
        elif status_filter == 'approved':
            qs = qs.filter(is_approved=True)
        return qs


class ReviewModerationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Review
        fields = ('id', 'is_approved')
        read_only_fields = ('id',)


class ReviewModerateView(generics.UpdateAPIView):
    """
    Owner-only: PATCH {"is_approved": true} to publish a pending review,
    or {"is_approved": false} to unpublish/hide it again.
    Requires the 'reviews' feature on the tenant's plan.
    """
    serializer_class = ReviewModerationSerializer
    permission_classes = [IsTenantOwner, HasTenantFeature('reviews')]

    def get_queryset(self):
        return Review.objects.filter(tenant=self.request.tenant).select_related('user')
