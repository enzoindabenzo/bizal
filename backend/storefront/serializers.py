from rest_framework import serializers
from .models import StorefrontPage, HeroSlide, PageSection


class StorefrontPageSerializer(serializers.ModelSerializer):
    class Meta:
        model = StorefrontPage
        fields = ('id', 'slug', 'title', 'body', 'is_published', 'order')

    def validate_slug(self, value):
        # The model enforces unique_together('tenant', 'slug'), but `tenant`
        # is deliberately excluded from `fields` (it's set server-side in
        # perform_create, never trusted from the client) — which means DRF's
        # automatic UniqueTogetherValidator never gets attached, since that
        # validator only fires for fields actually present on the serializer.
        # Without this, a duplicate slug skips validation entirely and falls
        # through to the DB, where the unique_together constraint raises an
        # unhandled IntegrityError -> 500, instead of a clean 400.
        request = self.context.get('request')
        tenant = getattr(request, 'tenant', None) if request else None
        if tenant is not None:
            qs = StorefrontPage.objects.filter(tenant=tenant, slug=value)
            if self.instance is not None:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError('Një faqe me këtë slug ekziston tashmë.')
        return value



class HeroSlideSerializer(serializers.ModelSerializer):
    class Meta:
        model = HeroSlide
        # BUG FIX: 'is_active' was missing from this list. The public
        # HeroSlideListView queryset already filters is_active=True server-side,
        # but the storefront frontend (index.html loadHeroAndStorefront()) does
        # its own client-side `slides.filter(s => s.is_active)` before rendering
        # the carousel. Since this serializer never emitted `is_active`, every
        # slide arrived as `s.is_active === undefined` (falsy), so the filter
        # discarded every slide unconditionally — hero slides never appeared on
        # any tenant's storefront, no matter how many were created and marked
        # active in django-admin.
        fields = ('id', 'title', 'subtitle', 'image', 'cta_label', 'cta_url', 'order', 'is_active')



class PageSectionSerializer(serializers.ModelSerializer):
    # Read-only for the client: whether this row is one of the fixed
    # locked rows (services grid, custom page body, auto Overview cards,
    # ...). Derived from lock_key rather than exposing lock_key itself,
    # since lock_key's specific value is an implementation detail the
    # frontend only needs as a boolean ("can I show a delete button?").
    locked = serializers.SerializerMethodField()

    class Meta:
        model = PageSection
        fields = (
            'id', 'page_key', 'section_type', 'title', 'subtitle', 'body',
            'image', 'cta_label', 'cta_url', 'data', 'hidden', 'order',
            'locked',
        )
        read_only_fields = ('page_key',)

    def get_locked(self, obj):
        return bool(obj.lock_key)

    def validate(self, attrs):
        # lock_key/page_key are never client-writable (see read_only_fields
        # and the absence of lock_key from `fields` entirely), but on
        # update we still need to stop a locked row from being switched to
        # a type that doesn't make sense for it -- e.g. flipping the
        # 'services grid' row's section_type away from 'locked' would let
        # the renderer treat it as a normal text/image/cta block and lose
        # the real grid it's supposed to represent.
        if self.instance and self.instance.lock_key and attrs.get('section_type', 'locked') != 'locked':
            attrs['section_type'] = 'locked'
        return attrs
