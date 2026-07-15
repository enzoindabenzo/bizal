import uuid
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from bizal.validators import validate_image_type


ROLE_CHOICES = [
    ('superadmin', 'Superadmin'),
    ('owner', 'Owner'),
    ('manager', 'Manager'),
    ('staff', 'Staff'),
    ('customer', 'Customer'),
]


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('Email is required')
        # M-1 FIX: Fully lowercase the email (both local part and domain)
        # before normalization and storage.  Django's normalize_email() only
        # lowercases the domain part.  Without this, "John@example.com" and
        # "john@example.com" resolve to different DB rows — causing login
        # failures when autocapitalize/autofill changes the case on mobile,
        # and silent duplicate accounts in staff-invite and tenant-signup flows.
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', 'superadmin')
        extra_fields.setdefault('is_active', True)
        # MEDIUM-3 FIX: enforce Django's documented contract — reject explicit False values
        # so create_superuser(..., is_staff=False) raises immediately rather than silently
        # producing a superadmin-labelled user without the corresponding permission flag.
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # NOTE: email is intentionally NOT globally unique. This is a multi-tenant
    # platform — the same person (same email) can have a separate account on
    # each tenant's portal (e.g. a customer of two different restaurants).
    # Uniqueness is enforced per-tenant via the UniqueConstraint below instead.
    # (Previously `unique=True` here meant a second tenant's registration with
    # an email already used elsewhere always failed with "user already exists",
    # and login then failed with "Invalid credentials for this portal" because
    # the existing row's `tenant` didn't match the portal being logged into.)
    email = models.EmailField()
    full_name = models.CharField(max_length=200, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True, validators=[validate_image_type])
    city          = models.CharField(max_length=100, blank=True)
    business_name = models.CharField(max_length=200, blank=True)

    # Per-channel opt-in flags for the account settings "Notifications" tab
    # (booking/order/reminder/promo/news). Keys are added on the frontend as
    # needed; any key not present here is treated as opted-in by the UI.
    notification_prefs = models.JSONField(default=dict, blank=True)

    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='customer')
    tenant = models.ForeignKey(
        'tenants.Tenant', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='users'
    )

    is_email_verified = models.BooleanField(
        default=False,
        help_text="True after the user clicks the email verification link sent at registration.",
    )
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['email', 'tenant'],
                name='accounts_user_unique_email_per_tenant',
            ),
        ]

    def __str__(self):
        return self.email

    @property
    def display_name(self):
        return self.full_name or self.email.split('@')[0]
