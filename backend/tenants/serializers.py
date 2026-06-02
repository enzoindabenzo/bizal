from rest_framework import serializers
from .models import Tenant


class TenantPublicSerializer(serializers.ModelSerializer):
    logo_url = serializers.SerializerMethodField()

    class Meta:
        model = Tenant
        fields = [
            'id', 'name', 'slug', 'site_title', 'tagline', 'business_type',
            'logo_url', 'primary_color', 'accent_color', 'font_family',
            'email', 'phone', 'whatsapp', 'address', 'city', 'country',
            'business_hours', 'facebook', 'instagram', 'tiktok', 'website',
            'story', 'founded_year', 'meta_description', 'plan',
        ]

    def get_logo_url(self, obj):
        if obj.logo:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.logo.url)
        return None


class TenantSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = [
            'name', 'site_title', 'tagline', 'business_type',
            'logo', 'primary_color', 'accent_color', 'font_family',
            'email', 'phone', 'whatsapp', 'address', 'city', 'country',
            'business_hours', 'facebook', 'instagram', 'tiktok', 'website',
            'story', 'founded_year', 'meta_description', 'meta_keywords',
        ]


class TenantAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at')


class TenantSignupSerializer(serializers.Serializer):
    business_name = serializers.CharField(max_length=200)
    slug = serializers.SlugField(max_length=80)
    business_type = serializers.ChoiceField(choices=[c[0] for c in [
        ('restaurant', ''), ('hotel', ''), ('car_rental', ''), ('clinic', ''),
        ('gym', ''), ('pharmacy', ''), ('barbershop', ''), ('market', ''),
        ('clothing', ''), ('spa', ''), ('lawyer', ''), ('language_school', ''),
    ]])
    owner_email = serializers.EmailField()
    owner_password = serializers.CharField(min_length=8, write_only=True)
    owner_name = serializers.CharField(max_length=200)

    def validate_slug(self, value):
        if Tenant.objects.filter(slug=value).exists():
            raise serializers.ValidationError('This subdomain is already taken.')
        return value
