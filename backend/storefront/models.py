from django.db import models
from bizal.base_models import TenantScopedUUIDModel
from bizal.validators import validate_image_type


class StorefrontPage(TenantScopedUUIDModel):
    """Custom pages (About, FAQ, Terms, etc.) for a tenant's public portal."""
    slug = models.SlugField(max_length=120)
    title = models.CharField(max_length=200)
    body = models.TextField()
    is_published = models.BooleanField(default=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        unique_together = ('tenant', 'slug')
        ordering = ['order', 'title']

    def __str__(self):
        return f"{self.tenant.slug} / {self.slug}"


class PageSection(TenantScopedUUIDModel):
    """
    A single content block on a tenant-portal page ('Overview', 'Services',
    'Menu', a custom StorefrontPage, etc). Two kinds of rows share this
    table:

    - Locked rows (lock_key non-blank) represent content that already exists
      on that page in some other form (the services grid, the menu grid, a
      custom page's body, the auto-generated 'Contact'/'Hours' cards on
      Overview, ...). They are seeded automatically the first time a page's
      sections are requested (see ensure_default_sections) and can be
      reordered and hidden like any other row, but can never be deleted --
      there would be nothing sensible left for that lock_key to represent.
    - Custom rows (lock_key blank) are blocks the tenant admin adds
      themselves (text, image, CTA, gallery, ...). Full control: create,
      edit, reorder, hide, delete.

    page_key identifies which page a row belongs to: one of the built-in
    keys in BUILTIN_PAGE_KEYS ('overview', 'services', 'menu', 'orders',
    'rentals', 'reviews', 'blog', 'contact'), or 'page:<slug>' for a
    tenant's own custom StorefrontPage.
    """
    SECTION_TYPES = [
        ('locked', 'Përmbajtje Origjinale'),
        ('text', 'Tekst'),
        ('image', 'Imazh'),
        ('cta', 'Thirrje për Veprim (CTA)'),
        ('gallery', 'Galeri Imazhesh'),
        ('spacer', 'Hapësirë'),
    ]

    page_key = models.CharField(max_length=40)
    lock_key = models.CharField(max_length=40, blank=True)
    section_type = models.CharField(max_length=20, choices=SECTION_TYPES, default='text')
    title = models.CharField(max_length=200, blank=True)
    subtitle = models.CharField(max_length=400, blank=True)
    body = models.TextField(blank=True)
    image = models.ImageField(upload_to='storefront/sections/', blank=True, validators=[validate_image_type])
    cta_label = models.CharField(max_length=80, blank=True)
    cta_url = models.CharField(max_length=300, blank=True)
    data = models.JSONField(blank=True, default=dict)
    hidden = models.BooleanField(default=False)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['page_key', 'order']

    def __str__(self):
        label = self.lock_key or self.title or self.section_type
        return f"{self.tenant.slug} / {self.page_key} / {label}"


class HeroSlide(TenantScopedUUIDModel):
    """Hero/banner carousel slides shown on the tenant portal home page."""
    title = models.CharField(max_length=200, blank=True)
    subtitle = models.CharField(max_length=400, blank=True)
    image = models.ImageField(upload_to='storefront/hero/', blank=True, validators=[validate_image_type])
    cta_label = models.CharField(max_length=80, blank=True)
    cta_url = models.CharField(max_length=300, blank=True)
    is_active = models.BooleanField(default=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"{self.tenant.slug} slide {self.order}"

