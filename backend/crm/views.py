from rest_framework import generics
from tenants.permissions import HasTenantRole, HasTenantFeature
from .models import Lead
from .serializers import LeadSerializer, LeadNoteSerializer


class LeadListCreateView(generics.ListCreateAPIView):
    serializer_class = LeadSerializer
    permission_classes = [HasTenantRole('receptionist', 'accountant'), HasTenantFeature('crm')]

    def get_queryset(self):
        qs = Lead.objects.filter(tenant=self.request.tenant).select_related('assigned_to')
        status = self.request.query_params.get('status')
        if status:
            qs = qs.filter(status=status)
        return qs

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)


class LeadDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = LeadSerializer
    permission_classes = [HasTenantRole('receptionist', 'accountant'), HasTenantFeature('crm')]

    def get_queryset(self):
        return Lead.objects.filter(tenant=self.request.tenant)


class LeadNoteCreateView(generics.CreateAPIView):
    serializer_class = LeadNoteSerializer
    permission_classes = [HasTenantRole('receptionist', 'accountant'), HasTenantFeature('crm')]

    def perform_create(self, serializer):
        # Verify the parent lead belongs to this tenant before attaching a
        # note to it. Without this check, a receptionist from Tenant A who
        # knows a Tenant B lead's UUID could POST to
        # /api/crm/leads/<B_UUID>/notes/ and corrupt B's CRM data.
        lead_pk = self.kwargs['lead_pk']
        try:
            Lead.objects.get(pk=lead_pk, tenant=self.request.tenant)
        except Lead.DoesNotExist:
            from rest_framework.exceptions import NotFound
            raise NotFound('Lead not found.')
        serializer.save(
            tenant=self.request.tenant,
            lead_id=lead_pk,
            author=self.request.user,
        )
