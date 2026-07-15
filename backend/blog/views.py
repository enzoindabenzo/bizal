from rest_framework import generics
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from .models import BlogPost, BlogTag, STATUS_PUBLISHED
from .serializers import BlogPostListSerializer, BlogPostDetailSerializer, BlogTagSerializer


class BlogPostListView(generics.ListAPIView):
    serializer_class = BlogPostListSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        qs = BlogPost.objects.filter(tenant=self.request.tenant, status=STATUS_PUBLISHED)
        tag = self.request.query_params.get('tag')
        if tag:
            qs = qs.filter(tags__slug=tag)
        return qs


class BlogPostDetailView(generics.RetrieveAPIView):
    serializer_class = BlogPostDetailSerializer
    permission_classes = [AllowAny]
    lookup_field = 'slug'

    def get_queryset(self):
        return BlogPost.objects.filter(tenant=self.request.tenant, status=STATUS_PUBLISHED)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        # Deduplicate view counts: only increment once per IP per post per hour.
        # This prevents bots and repeated refreshes from inflating stats.
        import hashlib
        from django.core.cache import cache
        from django.db.models import F
        # Use the rightmost non-private IP from X-Forwarded-For when behind
        # a CDN so that shared egress IPs (e.g. corporate proxies, Cloudflare
        # shared nodes) don't collapse all readers into one "already viewed"
        # bucket.  X-Real-IP (set by nginx to REMOTE_ADDR of the last hop)
        # is the safest single value when X-Forwarded-For is absent or untrusted.
        xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
        if xff:
            # FIX: the leftmost X-Forwarded-For entry is set by the client
            # itself and is fully spoofable — a bot can send a fresh fake
            # leftmost IP on every request to bypass the per-IP hourly dedup
            # cap and inflate view counts. Our nginx (the only public entry
            # point) appends the real client IP as the rightmost entry via
            # $proxy_add_x_forwarded_for, so that's the one entry a client
            # cannot forge. Use the rightmost entry as the trusted IP.
            ips = [x.strip() for x in xff.split(',')]
            ip_raw = ips[-1]
        else:
            ip_raw = (
                request.META.get('HTTP_X_REAL_IP')
                or request.META.get('REMOTE_ADDR', '')
            )
        ip_hash = hashlib.sha256(ip_raw.encode()).hexdigest()[:16]
        cache_key = f'blog_view:{instance.pk}:{ip_hash}'
        if not cache.get(cache_key):
            BlogPost.objects.filter(pk=instance.pk).update(view_count=F('view_count') + 1)
            cache.set(cache_key, True, 3600)
            instance.refresh_from_db()
        return Response(self.get_serializer(instance).data)


class BlogTagListView(generics.ListAPIView):
    serializer_class = BlogTagSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        return BlogTag.objects.filter(tenant=self.request.tenant)


from tenants.permissions import IsTenantOwner, HasTenantFeature


class BlogPostManageView(generics.ListCreateAPIView):
    """Owner: list all posts (inc drafts) and create new ones.
    Requires the 'blog' feature to be enabled for the tenant's plan."""
    permission_classes = [IsTenantOwner, HasTenantFeature('blog')]

    def get_serializer_class(self):
        return BlogPostDetailSerializer

    def get_queryset(self):
        return BlogPost.objects.filter(tenant=self.request.tenant).order_by('-created_at')

    def perform_create(self, serializer):
        from .models import STATUS_PUBLISHED, STATUS_DRAFT
        is_published = serializer.validated_data.pop('is_published', False)
        status_val = STATUS_PUBLISHED if is_published else STATUS_DRAFT
        serializer.save(tenant=self.request.tenant, status=status_val)


class BlogPostManageDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Owner: edit or delete a blog post by ID.
    Requires the 'blog' feature to be enabled for the tenant's plan."""
    permission_classes = [IsTenantOwner, HasTenantFeature('blog')]

    def get_serializer_class(self):
        return BlogPostDetailSerializer

    def get_queryset(self):
        return BlogPost.objects.filter(tenant=self.request.tenant)

    def perform_update(self, serializer):
        from .models import STATUS_PUBLISHED, STATUS_DRAFT
        is_pub = serializer.validated_data.pop(
            'is_published',
            serializer.instance.status == STATUS_PUBLISHED
        )
        serializer.save(
            status=STATUS_PUBLISHED if is_pub else STATUS_DRAFT
        )
