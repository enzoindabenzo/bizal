from rest_framework import serializers
from .models import BlogPost, BlogTag


class BlogTagSerializer(serializers.ModelSerializer):
    class Meta:
        model = BlogTag
        fields = ('id', 'name', 'slug')


class BlogPostListSerializer(serializers.ModelSerializer):
    tags = BlogTagSerializer(many=True, read_only=True)
    author_name = serializers.SerializerMethodField()
    cover_url = serializers.SerializerMethodField()

    class Meta:
        model = BlogPost
        fields = ('id', 'title', 'slug', 'excerpt', 'cover_url', 'tags',
                  'author_name', 'published_at', 'view_count')

    def get_author_name(self, obj):
        return obj.author.display_name if obj.author else 'BizAL'

    def get_cover_url(self, obj):
        if obj.cover:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.cover.url)
        return None


class BlogPostDetailSerializer(BlogPostListSerializer):
    class Meta(BlogPostListSerializer.Meta):
        fields = BlogPostListSerializer.Meta.fields + ('body',)
