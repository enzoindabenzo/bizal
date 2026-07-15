from django.db.models import Avg, Count
from django.utils.decorators import method_decorator
from rest_framework import generics, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from bizal.ratelimit_utils import ratelimit_decorator as _ratelimit_decorator
from .platform_models import PlatformReview
from .platform_serializers import PlatformReviewSerializer


class PlatformReviewListCreateView(generics.ListCreateAPIView):
    serializer_class = PlatformReviewSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        qs = PlatformReview.objects.filter(is_approved=True).order_by('-created_at')
        limit = self.request.query_params.get('limit')
        if limit:
            try:
                # v49 FIX: apply the same MAX_PAGE_SIZE cap (100) that was added
                # to the tenant-facing ReviewListCreateView (reviews/views.py H-1 FIX).
                # Without this, an unauthenticated caller can pass ?limit=999999 and
                # force a full table scan of all approved platform reviews into memory.
                # The dataset is small in practice, but the inconsistency is a latent
                # risk as the platform grows, and consistency with the peer view makes
                # the intent unambiguous.
                capped = min(int(limit), 100)
                return qs[:capped]
            except (ValueError, AssertionError):
                pass
        return qs

    def perform_create(self, serializer):
        user = self.request.user if self.request.user.is_authenticated else None
        serializer.save(user=user, is_approved=False)

    # MED-3 FIX: Rate-limit unauthenticated review submissions. The global DRF
    # throttle allows 60 anon requests/hour across all endpoints — far too generous
    # for a review-submission endpoint where a flood of fake submissions would fill
    # the moderation queue, DoS the admin UI, and insert unlimited DB rows.
    # 3 submissions per hour per IP is appropriate for a review form.
    @method_decorator(_ratelimit_decorator('3/h'))
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(
            {"detail": "Faleminderit! Vlerësimi juaj do shfaqet pas moderimit."},
            status=status.HTTP_201_CREATED,
        )


class PlatformReviewSummaryView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        qs = PlatformReview.objects.filter(is_approved=True)
        agg = qs.aggregate(average=Avg('rating'), total=Count('id'))

        distribution = {str(i): 0 for i in range(1, 6)}
        for row in qs.values('rating').annotate(count=Count('id')):
            distribution[str(row['rating'])] = row['count']

        return Response({
            "average": round(agg['average'] or 0, 1),
            "total":   agg['total'] or 0,
            "distribution": distribution,
        })

class PlatformReviewAdminView(generics.ListAPIView):
    """
    GET  /api/platform-reviews/admin/        — list all (pending + approved)
    PATCH /api/platform-reviews/admin/<id>/  — approve or reject
    """
    from rest_framework.permissions import IsAdminUser
    permission_classes = [IsAdminUser]
    serializer_class = PlatformReviewSerializer

    def get_queryset(self):
        qs = PlatformReview.objects.all()
        status_filter = self.request.query_params.get('status')
        if status_filter == 'pending':
            qs = qs.filter(is_approved=False)
        elif status_filter == 'approved':
            qs = qs.filter(is_approved=True)
        return qs


class PlatformReviewApproveView(generics.UpdateAPIView):
    """PATCH {"is_approved": true/false} to approve or reject a review."""
    from rest_framework.permissions import IsAdminUser
    from rest_framework import serializers as _s

    permission_classes = [IsAdminUser]
    http_method_names = ['patch']
    queryset = PlatformReview.objects.all()
    serializer_class = PlatformReviewSerializer

    def patch(self, request, *args, **kwargs):
        from django.utils import timezone
        review = self.get_object()
        approved = request.data.get('is_approved')
        if approved is None:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({'is_approved': 'This field is required.'})
        review.is_approved = bool(approved)
        review.approved_at = timezone.now() if review.is_approved else None
        review.save(update_fields=['is_approved', 'approved_at'])
        return Response(PlatformReviewSerializer(review).data)
