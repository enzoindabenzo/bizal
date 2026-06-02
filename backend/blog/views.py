from rest_framework import generics
from rest_framework.permissions import AllowAny
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
        BlogPost.objects.filter(pk=instance.pk).update(view_count=instance.view_count + 1)
        instance.refresh_from_db()
        serializer = self.get_serializer(instance)
        return self.get_response_class()(serializer.data) if False else \
            __import__('rest_framework.response', fromlist=['Response']).Response(serializer.data)


class BlogTagListView(generics.ListAPIView):
    serializer_class = BlogTagSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        return BlogTag.objects.filter(tenant=self.request.tenant)
