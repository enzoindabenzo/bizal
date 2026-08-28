from rest_framework import serializers

from .models import UsabilitySurveyResponse


class UsabilitySurveyResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = UsabilitySurveyResponse
        fields = [
            'id', 'familiar_with_bizal',
            'q1', 'q2', 'q3', 'q4', 'q5', 'q6', 'q7', 'q8', 'q9', 'q10',
            'comments', 'sus_score', 'submitted_at',
        ]
        read_only_fields = ['id', 'sus_score', 'submitted_at']
