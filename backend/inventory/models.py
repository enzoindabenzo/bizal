from django.db import models
from bizal.base_models import TenantScopedUUIDModel
from bizal.validators import validate_image_type


class ProductCategory(TenantScopedUUIDModel):
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100)
    image = models.ImageField(upload_to='categories/', blank=True, null=True, validators=[validate_image_type])

    class Meta:
        unique_together = ('tenant', 'slug')
        ordering = ('name',)

    def __str__(self):
        return self.name


class Product(TenantScopedUUIDModel):
    category = models.ForeignKey(ProductCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name='products')
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    sku = models.CharField(max_length=100, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    stock = models.PositiveIntegerField(default=0)
    low_stock_threshold = models.PositiveIntegerField(
        default=5,
        help_text='Stock at or below this level is flagged as low stock in the admin.',
    )
    image = models.ImageField(upload_to='products/', blank=True, null=True, validators=[validate_image_type])
    is_active = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    barcode = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def in_stock(self):
        return self.stock > 0

    @property
    def is_low_stock(self):
        return 0 < self.stock <= self.low_stock_threshold
