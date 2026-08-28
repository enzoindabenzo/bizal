from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from bizal.base_models import TenantScopedUUIDModel

REVIEW_TYPE_CHOICES = [
    ('business', 'Business'),
    ('product', 'Product / Service'),
    ('booking', 'Booking'),
]


class Review(TenantScopedUUIDModel):
    user = models.ForeignKey(
        'accounts.User', on_delete=models.CASCADE, related_name='reviews'
    )
    review_type = models.CharField(max_length=20, choices=REVIEW_TYPE_CHOICES, default='business')
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    comment = models.TextField()
    # NOTE: defaults to False (was True) — a review from any authenticated
    # customer used to go live on the public page immediately with zero
    # moderation. PlatformReview already used is_approved=False for the
    # same reason; this brings per-tenant reviews in line with that.
    is_approved = models.BooleanField(default=False)

    # Optional FK to a specific product/service (generic enough for any business)
    object_id = models.PositiveIntegerField(null=True, blank=True)
    object_label = models.CharField(max_length=200, blank=True)  # e.g. car name, room name

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user} → {self.tenant} ({self.rating}★)"
