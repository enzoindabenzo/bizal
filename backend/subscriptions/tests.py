from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from accounts.models import User
from tenants.models import Tenant
from .models import CustomerSubscription


class SubscriptionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(
            name='Gym Al', slug='gym-al', business_type='gym', plan='pro',
            is_active=True,
        )
        self.owner = User.objects.create_user(
            email='owner@gym.com', password='pass1234', tenant=self.tenant, role='owner',
        )
        self.customer = User.objects.create_user(
            email='customer@gym.com', password='pass1234', tenant=self.tenant, role='customer',
        )
        self.client.defaults['HTTP_HOST'] = 'gym-al.bizal.al'

    def test_owner_creates_subscription(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.post('/api/subscriptions/', {
            'customer': str(self.customer.pk),
            'name': 'Monthly Pass',
            'price': '3000.00',
            'frequency': 'monthly',
            'status': 'active',
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_customer_sees_own_subscriptions(self):
        CustomerSubscription.objects.create(
            tenant=self.tenant, customer=self.customer,
            name='Monthly Pass', price=3000, frequency='monthly', status='active',
        )
        self.client.force_authenticate(user=self.customer)
        resp = self.client.get('/api/subscriptions/mine/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data['results']), 1)

    def test_customer_cannot_list_all_subscriptions(self):
        self.client.force_authenticate(user=self.customer)
        resp = self.client.get('/api/subscriptions/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


# ── Expanded subscription tests ───────────────────────────────────────────────

from staff.models import StaffMember


def make_sub_tenant(slug, plan='pro', business_type='gym'):
    return Tenant.objects.create(
        name=slug.title(), slug=slug, plan=plan,
        business_type=business_type, is_active=True,
    )


def make_sub_user(email, tenant, role='owner', staff_role=None):
    user = User.objects.create_user(
        email=email, password='pass1234', tenant=tenant, role=role,
    )
    if staff_role:
        StaffMember.objects.create(tenant=tenant, user=user, role=staff_role, is_active=True)
    return user


class SubscriptionTenantScopingTest(TestCase):
    """Subscriptions must be isolated between tenants."""

    def setUp(self):
        self.client = APIClient()
        self.tenant = make_sub_tenant('gym-scope')
        self.other_tenant = make_sub_tenant('gym-other')
        self.owner = make_sub_user('owner@gym-scope.com', self.tenant)
        self.other_owner = make_sub_user('owner@gym-other.com', self.other_tenant)
        self.customer = make_sub_user('cust@gym-scope.com', self.tenant, role='customer')
        self.client.defaults['HTTP_HOST'] = 'gym-scope.bizal.al'
        CustomerSubscription.objects.create(
            tenant=self.tenant, customer=self.customer,
            name='Our Pass', price=2000, frequency='monthly', status='active',
        )
        other_cust = make_sub_user('cust@gym-other.com', self.other_tenant, role='customer')
        CustomerSubscription.objects.create(
            tenant=self.other_tenant, customer=other_cust,
            name='Their Pass', price=5000, frequency='monthly', status='active',
        )

    def test_owner_sees_only_own_tenant_subscriptions(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.get('/api/subscriptions/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        names = [s['name'] for s in resp.data['results']]
        self.assertIn('Our Pass', names)
        self.assertNotIn('Their Pass', names)

    def test_cross_tenant_subscription_detail_returns_404(self):
        other_cust = make_sub_user('c2@gym-other.com', self.other_tenant, role='customer')
        other_sub = CustomerSubscription.objects.create(
            tenant=self.other_tenant, customer=other_cust,
            name='Secret Sub', price=1000, frequency='weekly', status='active',
        )
        self.client.force_authenticate(user=self.owner)
        resp = self.client.get(f'/api/subscriptions/{other_sub.pk}/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class SubscriptionCrossTenantCustomerTest(TestCase):
    """
    SECURITY: Creating a subscription with a customer from a different tenant
    must be rejected. Without the perform_create guard, DRF's unscoped
    PrimaryKeyRelatedField would accept any User UUID.
    """

    def setUp(self):
        self.client = APIClient()
        self.tenant = make_sub_tenant('gym-xsec')
        self.other_tenant = make_sub_tenant('gym-xsec-other')
        self.owner = make_sub_user('owner@gym-xsec.com', self.tenant)
        self.other_customer = make_sub_user('cust@gym-xsec-other.com', self.other_tenant, role='customer')
        self.client.defaults['HTTP_HOST'] = 'gym-xsec.bizal.al'
        self.client.force_authenticate(user=self.owner)

    def test_cross_tenant_customer_is_rejected(self):
        resp = self.client.post('/api/subscriptions/', {
            'customer': str(self.other_customer.pk),
            'name': 'Cross-tenant Attack',
            'price': '1.00',
            'frequency': 'monthly',
            'status': 'active',
        })
        self.assertIn(resp.status_code, [status.HTTP_400_BAD_REQUEST, status.HTTP_403_FORBIDDEN])
        self.assertFalse(CustomerSubscription.objects.filter(name='Cross-tenant Attack').exists())


class SubscriptionRolePermissionTest(TestCase):
    """Role-based access: accountant yes, plain customer no."""

    def setUp(self):
        self.client = APIClient()
        self.tenant = make_sub_tenant('gym-roles')
        self.client.defaults['HTTP_HOST'] = 'gym-roles.bizal.al'

    def test_accountant_can_list_subscriptions(self):
        accountant = make_sub_user('acc@gym-roles.com', self.tenant, role='customer', staff_role='accountant')
        self.client.force_authenticate(user=accountant)
        resp = self.client.get('/api/subscriptions/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_plain_customer_cannot_list_subscriptions(self):
        customer = make_sub_user('cust@gym-roles.com', self.tenant, role='customer')
        self.client.force_authenticate(user=customer)
        resp = self.client.get('/api/subscriptions/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_cannot_access(self):
        resp = self.client.get('/api/subscriptions/')
        self.assertIn(resp.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])


class SubscriptionFilterTest(TestCase):
    """Query-param filtering by status and customer."""

    def setUp(self):
        self.client = APIClient()
        self.tenant = make_sub_tenant('gym-filter')
        self.owner = make_sub_user('owner@gym-filter.com', self.tenant)
        self.cust1 = make_sub_user('c1@gym-filter.com', self.tenant, role='customer')
        self.cust2 = make_sub_user('c2@gym-filter.com', self.tenant, role='customer')
        self.client.defaults['HTTP_HOST'] = 'gym-filter.bizal.al'
        self.client.force_authenticate(user=self.owner)
        CustomerSubscription.objects.create(
            tenant=self.tenant, customer=self.cust1,
            name='Active Sub', price=1000, frequency='monthly', status='active',
        )
        CustomerSubscription.objects.create(
            tenant=self.tenant, customer=self.cust2,
            name='Cancelled Sub', price=500, frequency='yearly', status='cancelled',
        )

    def test_filter_by_status(self):
        resp = self.client.get('/api/subscriptions/?status=active')
        names = [s['name'] for s in resp.data['results']]
        self.assertIn('Active Sub', names)
        self.assertNotIn('Cancelled Sub', names)

    def test_filter_by_customer(self):
        resp = self.client.get(f'/api/subscriptions/?customer={self.cust1.pk}')
        names = [s['name'] for s in resp.data['results']]
        self.assertIn('Active Sub', names)
        self.assertNotIn('Cancelled Sub', names)
