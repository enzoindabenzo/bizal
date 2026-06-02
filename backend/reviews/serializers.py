from rest_framework import serializers
from .models import Review


class ReviewSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()

    class Meta:
        model = Review
        fields = ('id', 'user_name', 'review_type', 'rating', 'comment',
                  'object_label', 'is_approved', 'created_at')
        read_only_fields = ('id', 'user_name', 'is_approved', 'created_at')

    def get_user_name(self, obj):
        return obj.user.display_name

    def validate_comment(self, value):
        if not value.strip():
            raise serializers.ValidationError('Comment cannot be empty.')
        return value
