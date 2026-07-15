from rest_framework import serializers
from .models import ActivityLog


class ActivityLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = ActivityLog
        fields = (
            'id', 'actor_name', 'verb', 'description',
            'target_type', 'target_id', 'metadata', 'created_at',
        )
