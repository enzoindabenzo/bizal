from rest_framework import serializers
from .models import StaffMember, StaffSchedule


class StaffScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = StaffSchedule
        fields = ('id', 'day', 'start_time', 'end_time')


class StaffMemberSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(source='user.display_name', read_only=True)
    email = serializers.EmailField(source='user.email', read_only=True)
    schedules = StaffScheduleSerializer(many=True, read_only=True)

    class Meta:
        model = StaffMember
        fields = ('id', 'full_name', 'email', 'role', 'position', 'is_active', 'hire_date', 'schedules')
