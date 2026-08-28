from django.db.models import Prefetch
from rest_framework import generics
from tenants.permissions import HasTenantRole, HasTenantFeature
from .models import Lead, LeadNote
from .serializers import LeadSerializer, LeadNoteSerializer


class LeadListCreateView(generics.ListCreateAPIView):
    serializer_class = LeadSerializer
    permission_classes = [HasTenantRole('receptionist', 'accountant'), HasTenantFeature('crm')]

    def get_queryset(self):
        # N+1 FIX: LeadSerializer nests `lead_notes = LeadNoteSerializer(many=True)`,
        # so without prefetch_related here, DRF issues one extra query per
        # Lead in the page (obj.lead_notes.all()) — a paginated list of 20
        # leads becomes 21 queries instead of 2. Every other list view in
        # this codebase that nests a many=True relation prefetches it
        # (see billing.InvoiceListCreateView, hotels.RoomTypeListView,
        # menu.MenuListView, staff's roster view); this one was missed.
        #
        # A plain prefetch_related('lead_notes') isn't enough on its own:
        # LeadNoteSerializer.author_name reads note.author.display_name per
        # note, so without select_related('author') on the prefetch queryset
        # itself, that becomes a second layer of N+1 (one query per note
        # instead of one query per lead). Use an explicit Prefetch object so
        # the note->author join happens in the same prefetch query.
        qs = Lead.objects.filter(tenant=self.request.tenant) \
            .select_related('assigned_to') \
            .prefetch_related(
                Prefetch('lead_notes', queryset=LeadNote.objects.select_related('author'))
            )
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
