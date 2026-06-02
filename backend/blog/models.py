from django.db import models
from django.utils.text import slugify
from bizal.base_models import TenantScopedUUIDModel

STATUS_DRAFT = 'draft'
STATUS_PUBLISHED = 'published'
STATUS_ARCHIVED = 'archived'

STATUS_CHOICES = [
    (STATUS_DRAFT, 'Draft'),
    (STATUS_PUBLISHED, 'Published'),
    (STATUS_ARCHIVED, 'Archived'),
]


class BlogTag(models.Model):
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.CASCADE, related_name='blog_tags')
    name = models.CharField(max_length=60)
    slug = models.SlugField(max_length=60)

    class Meta:
        unique_together = ('tenant', 'slug')

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class BlogPost(TenantScopedUUIDModel):
    author = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, related_name='blog_posts')
    title = models.CharField(max_length=300)
    slug = models.SlugField(max_length=300)
    excerpt = models.TextField(blank=True)
    body = models.TextField()
    cover = models.ImageField(upload_to='blog/covers/', blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    tags = models.ManyToManyField(BlogTag, blank=True, related_name='posts')
    published_at = models.DateTimeField(null=True, blank=True)
    view_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-published_at', '-created_at']
        unique_together = ('tenant', 'slug')

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title
