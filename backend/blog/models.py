from django.db import models
from django.utils.text import slugify
from bizal.base_models import TenantScopedUUIDModel
from bizal.validators import validate_image_type

STATUS_DRAFT = 'draft'
STATUS_PUBLISHED = 'published'
STATUS_ARCHIVED = 'archived'

STATUS_CHOICES = [
    (STATUS_DRAFT, 'Draft'),
    (STATUS_PUBLISHED, 'Published'),
    (STATUS_ARCHIVED, 'Archived'),
]


class BlogTag(models.Model):
    # NOTE: the tenant FK is intentionally non-nullable here. The previous
    # null=True, blank=True allowed orphaned tags with no tenant, which
    # bypasses the cascade guarantee. If a main-platform blog (outside any
    # tenant) is ever needed, introduce a separate PlatformBlogTag model
    # following the pattern in reviews/platform_models.py.
    tenant = models.ForeignKey(
        'tenants.Tenant', on_delete=models.CASCADE,
        related_name='blog_tags'
    )
    name = models.CharField(max_length=60)
    slug = models.SlugField(max_length=60)

    class Meta:
        unique_together = ('tenant', 'slug')
        ordering = ['name']

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class BlogPost(TenantScopedUUIDModel):
    # NOTE: previously used UUIDModel + TimeStampedModel with a manually
    # declared nullable tenant FK. Switched to TenantScopedUUIDModel so
    # the tenant FK is non-nullable and the cascade + related_name pattern
    # is consistent with every other model in the codebase. If a
    # main-platform blog (no tenant) is ever needed, add a PlatformBlogPost
    # model in platform_models.py, mirroring reviews/platform_models.py.
    author = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, related_name='blog_posts')
    title = models.CharField(max_length=300)
    slug = models.SlugField(max_length=300)
    excerpt = models.TextField(blank=True)
    body = models.TextField()
    cover = models.ImageField(upload_to='blog/covers/', blank=True, null=True, validators=[validate_image_type])
    # BUG FIX: previously defaulted to STATUS_DRAFT. Every other storefront
    # content model (HeroSlide.is_active, StorefrontPage.is_published)
    # defaults to visible, so a post created directly in django-admin — where
    # there's no "Publikuar" checkbox UX, just a plain status dropdown that's
    # easy to miss — silently stayed invisible on the tenant site with no
    # obvious explanation ("blog posts don't reflect in tenant"). Defaulting
    # to published keeps admin-created posts consistent with the rest of the
    # storefront content types; an editor can still explicitly set status
    # back to Draft/Archived to hide a post.
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PUBLISHED)
    tags = models.ManyToManyField(BlogTag, blank=True, related_name='posts')
    published_at = models.DateTimeField(null=True, blank=True)
    view_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-published_at', '-created_at']
        unique_together = ('tenant', 'slug')

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
        if self.status == STATUS_PUBLISHED and not self.published_at:
            from django.utils import timezone
            self.published_at = timezone.now()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title

    @property
    def is_published(self):
        """
        Convenience property derived from `status` — NOT a DB column.
        Use `.filter(status=STATUS_PUBLISHED)` (or `.exclude(...)`) for
        queryset filtering; `.filter(is_published=True)` will raise a
        FieldError since the ORM has no column to filter on. The
        serializer's `is_published` field (see blog/serializers.py) reads
        and writes this property for the API, but that's a serializer-level
        concept only — it doesn't make this filterable at the DB level.
        """
        return self.status == STATUS_PUBLISHED