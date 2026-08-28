from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from bizal.base_models import TimeStampedModel


class PlatformReview(TimeStampedModel):
    """Testimonial about BizAL shown on the public landing page."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='platform_reviews',
    )
    reviewer_name = models.CharField(max_length=120)
    business_name = models.CharField(max_length=200, blank=True)
    business_type = models.CharField(max_length=80, blank=True)
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    comment = models.TextField()
    is_approved = models.BooleanField(default=False, db_index=True)
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Platform Review'
        verbose_name_plural = 'Platform Reviews'

    def __str__(self):
        return f"{self.reviewer_name} ({self.rating}★) — {self.business_name or 'anonymous'}"