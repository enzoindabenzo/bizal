from rest_framework import serializers
from .models import Lead, LeadNote


class LeadNoteSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source='author.display_name', read_only=True)

    class Meta:
        model = LeadNote
        fields = ('id', 'author_name', 'body', 'created_at')
        read_only_fields = ('created_at',)


class LeadSerializer(serializers.ModelSerializer):
    lead_notes = LeadNoteSerializer(many=True, read_only=True)
    assigned_to_name = serializers.CharField(source='assigned_to.display_name', read_only=True)

    class Meta:
        model = Lead
        fields = (
            'id', 'name', 'email', 'phone', 'source', 'status',
            'notes', 'assigned_to', 'assigned_to_name', 'lead_notes', 'created_at',
        )
        read_only_fields = ('created_at',)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # IDOR fix: scope the assigned_to FK to staff/users belonging to the
        # current tenant. Without this, a tenant owner could assign a lead to
        # a user from another tenant by supplying a foreign UUID, leaking that
        # user's display_name in the response and creating a cross-tenant
        # data association.
        request = self.context.get('request')
        if request and hasattr(request, 'tenant') and request.tenant:
            from accounts.models import User
            self.fields['assigned_to'].queryset = User.objects.filter(
                tenant=request.tenant
            )
