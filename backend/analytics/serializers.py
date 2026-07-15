from rest_framework import serializers
from .models import AnalyticsEvent


class AnalyticsEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnalyticsEvent
        fields = ('id', 'event_type', 'page', 'referrer', 'metadata', 'created_at')
        read_only_fields = ('id', 'created_at')
