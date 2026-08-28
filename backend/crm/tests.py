from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.db import connection
from rest_framework.test import APIClient
from rest_framework import status
from accounts.models import User
from tenants.models import Tenant
from .models import Lead


class CRMTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(
            name='Cars SH', slug='hertz', business_type='car_rental', plan='enterprise',
            is_active=True,
        )
        self.owner = User.objects.create_user(
            email='owner@hertz.com', password='pass1234', tenant=self.tenant, role='owner',
        )
        self.client.defaults['HTTP_HOST'] = 'hertz.bizal.al'
        self.client.force_authenticate(user=self.owner)

    def test_create_lead(self):
        resp = self.client.post('/api/crm/leads/', {
            'name': 'Arben Hoxha', 'email': 'arben@test.com', 'source': 'website', 'status': 'new',
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['name'], 'Arben Hoxha')

    def test_list_leads_scoped_to_tenant(self):
        other_tenant = Tenant.objects.create(name='Other', slug='other', business_type='gym', plan='pro', is_active=True)
        Lead.objects.create(tenant=self.tenant, name='Our Lead', status='new', source='website')
        Lead.objects.create(tenant=other_tenant, name='Their Lead', status='new', source='website')
        resp = self.client.get('/api/crm/leads/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        names = [r['name'] for r in resp.data['results']]
        self.assertIn('Our Lead', names)
        self.assertNotIn('Their Lead', names)

    def test_filter_leads_by_status(self):
        Lead.objects.create(tenant=self.tenant, name='Won', status='won', source='referral')
        Lead.objects.create(tenant=self.tenant, name='New', status='new', source='website')
        resp = self.client.get('/api/crm/leads/?status=won')
        names = [r['name'] for r in resp.data['results']]
        self.assertIn('Won', names)
        self.assertNotIn('New', names)

    def test_add_note_to_lead(self):
        lead = Lead.objects.create(tenant=self.tenant, name='Test Lead', status='new', source='website')
        resp = self.client.post(f'/api/crm/leads/{lead.pk}/notes/', {'body': 'Called, left voicemail.'})
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_list_leads_does_not_n_plus_1_on_lead_notes(self):
        """
        Regression test: LeadSerializer nests
        `lead_notes = LeadNoteSerializer(many=True)`. Without
        prefetch_related('lead_notes') on the list view's queryset, DRF
        issues one extra query per lead in the page (obj.lead_notes.all()),
        so query count scales with the number of leads returned instead of
        staying flat. Create two different page sizes and assert the query
        count doesn't grow between them.
        """
        from importlib import import_module
        LeadNoteModel = import_module('crm.models').LeadNote

        def make_leads(n, notes_each=2):
            for i in range(n):
                lead = Lead.objects.create(
                    tenant=self.tenant, name=f'Lead {i}', status='new', source='website',
                )
                for j in range(notes_each):
                    LeadNoteModel.objects.create(
                        tenant=self.tenant, lead=lead, author=self.owner, body=f'note {j}',
                    )

        make_leads(3)
        with CaptureQueriesContext(connection) as ctx:
            resp = self.client.get('/api/crm/leads/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        small_count = len(ctx.captured_queries)

        Lead.objects.all().delete()
        make_leads(15)
        with CaptureQueriesContext(connection) as ctx:
            resp = self.client.get('/api/crm/leads/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        large_count = len(ctx.captured_queries)

        # With prefetch_related, query count is constant regardless of how
        # many leads/notes are returned. Without it, 15 leads would add ~15
        # more queries than 3 leads did. Allow a small fixed slack (e.g. for
        # pagination COUNT queries) rather than requiring an exact match.
        self.assertLessEqual(
            large_count, small_count + 2,
            f"Query count grew with lead count ({small_count} -> {large_count}); "
            "looks like an N+1 on lead_notes.",
        )


# ── Expanded CRM test suite ───────────────────────────────────────────────────

from staff.models import StaffMember
from .models import LeadNote


def make_crm_tenant(slug, plan='enterprise', business_type='car_rental'):
    return Tenant.objects.create(
        name=slug.title(), slug=slug, plan=plan,
        business_type=business_type, is_active=True,
    )


def make_crm_user(email, tenant, role='owner', staff_role=None):
    user = User.objects.create_user(
        email=email, password='pass1234', tenant=tenant, role=role,
    )
    if staff_role:
        StaffMember.objects.create(tenant=tenant, user=user, role=staff_role, is_active=True)
    return user


class CRMLeadDetailTest(TestCase):
    """RetrieveUpdateDestroy tests for individual leads."""

    def setUp(self):
        self.client = APIClient()
        self.tenant = make_crm_tenant('crm-detail')
        self.owner = make_crm_user('owner@crm-detail.com', self.tenant)
        self.client.defaults['HTTP_HOST'] = 'crm-detail.bizal.al'
        self.client.force_authenticate(user=self.owner)
        self.lead = Lead.objects.create(
            tenant=self.tenant, name='Detail Lead', status='new', source='website',
        )

    def test_owner_can_retrieve_lead(self):
        resp = self.client.get(f'/api/crm/leads/{self.lead.pk}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['name'], 'Detail Lead')

    def test_owner_can_update_lead_status(self):
        resp = self.client.patch(f'/api/crm/leads/{self.lead.pk}/', {'status': 'qualified'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, 'qualified')

    def test_owner_can_delete_lead(self):
        resp = self.client.delete(f'/api/crm/leads/{self.lead.pk}/')
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Lead.objects.filter(pk=self.lead.pk).exists())

    def test_cross_tenant_lead_detail_returns_404(self):
        other_tenant = make_crm_tenant('crm-other')
        other_lead = Lead.objects.create(
            tenant=other_tenant, name='Other Tenant Lead', status='new', source='referral',
        )
        resp = self.client.get(f'/api/crm/leads/{other_lead.pk}/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class CRMRolePermissionTest(TestCase):
    """Permission checks: receptionist/accountant can access, plain customer cannot."""

    def setUp(self):
        self.client = APIClient()
        self.tenant = make_crm_tenant('crm-roles')
        self.client.defaults['HTTP_HOST'] = 'crm-roles.bizal.al'
        self.lead = Lead.objects.create(
            tenant=self.tenant, name='Role Test Lead', status='new', source='walk_in',
        )

    def test_receptionist_can_list_leads(self):
        receptionist = make_crm_user('rec@crm-roles.com', self.tenant, role='customer', staff_role='receptionist')
        self.client.force_authenticate(user=receptionist)
        resp = self.client.get('/api/crm/leads/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_accountant_can_create_lead(self):
        accountant = make_crm_user('acc@crm-roles.com', self.tenant, role='customer', staff_role='accountant')
        self.client.force_authenticate(user=accountant)
        resp = self.client.post('/api/crm/leads/', {
            'name': 'Accountant Lead', 'source': 'referral', 'status': 'new',
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_plain_customer_cannot_access_leads(self):
        customer = make_crm_user('cust@crm-roles.com', self.tenant, role='customer')
        self.client.force_authenticate(user=customer)
        resp = self.client.get('/api/crm/leads/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_cannot_access_leads(self):
        resp = self.client.get('/api/crm/leads/')
        self.assertIn(resp.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])


class CRMFeatureGatingTest(TestCase):
    """Tenants without the crm feature must be blocked."""

    def test_no_crm_feature_returns_403(self):
        # 'starter' plan + 'market' business_type has no crm feature
        tenant = make_crm_tenant('crm-nofeature', plan='starter', business_type='market')
        owner = make_crm_user('owner@crm-nofeature.com', tenant)
        client = APIClient()
        client.defaults['HTTP_HOST'] = 'crm-nofeature.bizal.al'
        client.force_authenticate(user=owner)
        resp = client.get('/api/crm/leads/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


class CRMLeadNoteTest(TestCase):
    """LeadNote creation, authorship, and cross-tenant security."""

    def setUp(self):
        self.client = APIClient()
        self.tenant = make_crm_tenant('crm-notes')
        self.owner = make_crm_user('owner@crm-notes.com', self.tenant)
        self.client.defaults['HTTP_HOST'] = 'crm-notes.bizal.al'
        self.client.force_authenticate(user=self.owner)
        self.lead = Lead.objects.create(
            tenant=self.tenant, name='Note Target', status='new', source='website',
        )

    def test_note_author_is_set_to_requesting_user(self):
        resp = self.client.post(f'/api/crm/leads/{self.lead.pk}/notes/', {'body': 'Left voicemail.'})
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        note = LeadNote.objects.get(lead=self.lead)
        self.assertEqual(note.author, self.owner)

    def test_cross_tenant_note_on_other_tenant_lead_returns_404(self):
        """
        SECURITY: An owner from Tenant A must not be able to attach a note
        to a lead belonging to Tenant B, even if they know the UUID.
        This is the cross-tenant vulnerability fix: LeadNoteCreateView.perform_create
        now verifies lead_pk belongs to request.tenant before saving.
        """
        other_tenant = make_crm_tenant('crm-other-notes')
        other_lead = Lead.objects.create(
            tenant=other_tenant, name='Other Tenant Lead', status='new', source='referral',
        )
        resp = self.client.post(
            f'/api/crm/leads/{other_lead.pk}/notes/',
            {'body': 'Cross-tenant attack'},
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        # Confirm no note was actually created
        self.assertFalse(LeadNote.objects.filter(lead=other_lead).exists())
