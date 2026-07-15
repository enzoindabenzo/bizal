from rest_framework import serializers
from .models import ContactMessage, PlatformInquiry


class ContactMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactMessage
        fields = ('id', 'name', 'email', 'phone', 'subject', 'message', 'is_read', 'replied_at', 'created_at')
        read_only_fields = ('id', 'is_read', 'replied_at', 'created_at')


class PlatformInquirySerializer(serializers.ModelSerializer):
    class Meta:
        model = PlatformInquiry
        fields = ('id', 'name', 'email', 'phone', 'subject', 'message', 'created_at')
        read_only_fields = ('id', 'created_at')
