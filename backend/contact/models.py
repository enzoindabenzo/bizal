from django.db import models
from bizal.base_models import TenantScopedUUIDModel, TimeStampedModel, UUIDModel


class ContactMessage(TenantScopedUUIDModel):
    name = models.CharField(max_length=200)
    email = models.EmailField()
    phone = models.CharField(max_length=30, blank=True)
    subject = models.CharField(max_length=300, blank=True)
    message = models.TextField()
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    is_read = models.BooleanField(default=False)
    replied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} → {self.tenant} ({self.created_at:%Y-%m-%d})"


class PlatformInquiry(TimeStampedModel, UUIDModel):
    """Contact submissions from the main marketing site (bizal.al), which has
    no tenant context. Kept separate from ContactMessage because that model's
    tenant FK is non-nullable (TenantScopedUUIDModel)."""
    name = models.CharField(max_length=200)
    email = models.EmailField()
    phone = models.CharField(max_length=30, blank=True)
    subject = models.CharField(max_length=300, blank=True)
    message = models.TextField()
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.created_at:%Y-%m-%d})"
