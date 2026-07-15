from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from .models import User


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = ('email', 'password', 'full_name', 'phone')

    def validate_email(self, value):
        # M-1 FIX: normalize the email to lowercase at the serializer level so
        # that the value stored via create_user() always matches what a user
        # types on any device regardless of autocapitalize/autofill behaviour.
        value = value.strip().lower()
        # Email is no longer globally unique on the model (see accounts.User) —
        # the same email can have a separate account per tenant. Re-implement
        # the "already registered" check scoped to the tenant this request is
        # registering against, instead of relying on the (removed) global
        # unique=True constraint that DRF used to auto-validate here.
        request = self.context.get('request')
        tenant = getattr(request, 'tenant', None) if request else None
        if User.objects.filter(email=value, tenant=tenant).exists():
            raise serializers.ValidationError('Ka tashmë një user me këtë email.')
        return value

    def validate_password(self, value):
        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError as DjangoValidationError
        # min_length=8 above is a quick first check; this runs the full set
        # of AUTH_PASSWORD_VALIDATORS configured in settings (common-password
        # list, similarity-to-email check, purely-numeric check), which
        # registration previously skipped entirely.
        temp_user = User(
            email=(self.initial_data.get('email', '') or '').strip().lower(),
            full_name=self.initial_data.get('full_name', ''),
        )
        try:
            validate_password(value, user=temp_user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))
        return value

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)


class UserProfileSerializer(serializers.ModelSerializer):
    tenant_name = serializers.SerializerMethodField()
    tenant_slug = serializers.SerializerMethodField()
    staff_role = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            'id', 'email', 'full_name', 'phone', 'avatar',
            'role', 'staff_role', 'tenant_name', 'tenant_slug', 'city', 'business_name', 'created_at',
            'is_staff',
        )
        read_only_fields = (
            'id', 'email', 'role', 'created_at', 'is_staff',
            # NOTE: is_email_verified is intentionally NOT in fields above.
            # If it is ever added to fields, it MUST also be listed here to
            # prevent any authenticated user from self-verifying via PATCH /api/auth/me/.
        )

    def get_tenant_name(self, obj):
        return obj.tenant.name if obj.tenant else None

    def get_tenant_slug(self, obj):
        return obj.tenant.slug if obj.tenant else None

    def get_staff_role(self, obj):
        """
        Granular sub-role from StaffMember (e.g. 'receptionist',
        'accountant'), distinct from the broad accounts.User.role
        ('owner'/'manager'/'staff'/'customer'). Used by the admin UI to
        show a more specific role badge. None if the user has no active
        staff profile (owners/managers/customers).
        """
        profile = getattr(obj, 'staff_profile', None)
        if profile is not None and profile.is_active:
            return profile.role
        return None


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        # These go INTO the JWT so JS can decode them client-side
        token['email'] = user.email
        token['full_name'] = user.full_name or ''
        token['role'] = user.role
        token['tenant_slug'] = user.tenant.slug if user.tenant else None
        token['is_staff'] = user.is_staff   # CRIT-1 FIX: required by frontend role-gating (see index.html/tenant_admin.html ROLE checks)
        return token

    def validate(self, attrs):
        # M-1 FIX: lowercase the submitted username (email) before the parent
        # class performs the get_by_natural_key() lookup, so that a user who
        # registered as "John@example.com" can log in as "john@example.com".
        # simplejwt reads the username from attrs[self.username_field].
        if self.username_field in attrs:
            attrs[self.username_field] = attrs[self.username_field].strip().lower()
        data = super().validate(attrs)
        user = self.user
        # This goes in the LOGIN RESPONSE BODY (for JS to use immediately)
        data['user'] = {
            'id': str(user.id),
            'email': user.email,
            'full_name': user.full_name,
            'role': user.role,
            'tenant_slug': user.tenant.slug if user.tenant else None,
            # Lets the frontend send a tenant owner who never finished the
            # setup wizard back to /onboarding/ (main domain) instead of
            # their subdomain, which won't be fully usable yet.
            'onboarding_complete': user.tenant.onboarding_complete if user.tenant else None,
        }
        return data