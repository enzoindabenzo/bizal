from rest_framework import serializers
from .platform_models import PlatformReview


class PlatformReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlatformReview
        fields = [
            'id',
            'reviewer_name',
            'business_name',
            'business_type',
            'rating',
            'comment',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at']

    def validate_rating(self, value):
        if not 1 <= value <= 5:
            raise serializers.ValidationError("Vlerësimi duhet të jetë ndërmjet 1 dhe 5.")
        return value

    def validate_comment(self, value):
        if len(value.strip()) < 10:
            raise serializers.ValidationError("Komenti duhet të ketë të paktën 10 karaktere.")
        return value.strip()

    def validate_reviewer_name(self, value):
        if len(value.strip()) < 2:
            raise serializers.ValidationError("Emri duhet të ketë të paktën 2 karaktere.")
        return value.strip()