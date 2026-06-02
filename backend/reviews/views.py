from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from tenants.permissions import TenantDomainOnly
from .models import Review
from .serializers import ReviewSerializer


class ReviewListCreateView(generics.ListCreateAPIView):
    serializer_class = ReviewSerializer

    def get_permissions(self):
        if self.request.method == 'GET':
            return [AllowAny()]
        return [IsAuthenticated(), TenantDomainOnly()]

    def get_queryset(self):
        qs = Review.objects.filter(tenant=self.request.tenant, is_approved=True)
        limit = self.request.query_params.get('limit')
        if limit:
            try:
                qs = qs[:int(limit)]
            except ValueError:
                pass
        return qs

    def perform_create(self, serializer):
        serializer.save(
            tenant=self.request.tenant,
            user=self.request.user,
        )
