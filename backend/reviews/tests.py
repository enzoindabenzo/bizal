from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from tenants.models import Tenant, PLAN_PRO
from accounts.models import User
from .models import Review


def make_tenant(slug, active=True):
    return Tenant.objects.create(name=slug.title(), slug=slug, plan=PLAN_PRO, is_active=active)


def make_user(email, tenant=None, role='customer'):
    return User.objects.create_user(email=email, password='pass1234', tenant=tenant, role=role)


class ReviewTenantIsolationTest(TestCase):
    def setUp(self):
        self.t1 = make_tenant('alpha')
        self.t2 = make_tenant('beta')
        self.u1 = make_user('u1@alpha.com', self.t1)
        self.u2 = make_user('u2@beta.com', self.t2)
        Review.objects.create(tenant=self.t1, user=self.u1, rating=5, comment='Great!', review_type='business')
        Review.objects.create(tenant=self.t2, user=self.u2, rating=4, comment='Good!', review_type='business')

    def test_tenant_only_sees_own_reviews(self):
        client = APIClient()
        client.defaults['HTTP_HOST'] = 'alpha.bizal.al'
        resp = client.get('/api/reviews/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data['results']), 1)
        self.assertEqual(resp.data['results'][0]['comment'], 'Great!')

    def test_cross_tenant_review_invisible(self):
        client = APIClient()
        client.defaults['HTTP_HOST'] = 'beta.bizal.al'
        resp = client.get('/api/reviews/')
        for r in resp.data['results']:
            self.assertNotEqual(r['comment'], 'Great!')


class ReviewAPITest(TestCase):
    def setUp(self):
        self.tenant = make_tenant('myshop')
        self.user = make_user('buyer@myshop.com', self.tenant)
        self.client = APIClient()
        self.client.defaults['HTTP_HOST'] = 'myshop.bizal.al'

    def _login(self):
        resp = self.client.post('/api/auth/login/', {'email': 'buyer@myshop.com', 'password': 'pass1234'})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")

    def test_unauthenticated_post_rejected(self):
        resp = self.client.post('/api/reviews/', {'rating': 5, 'comment': 'Nice', 'review_type': 'business'})
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_authenticated_post_creates_review(self):
        self._login()
        resp = self.client.post('/api/reviews/', {'rating': 4, 'comment': 'Lovely', 'review_type': 'business'})
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_empty_comment_rejected(self):
        self._login()
        resp = self.client.post('/api/reviews/', {'rating': 3, 'comment': '   ', 'review_type': 'business'})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rating_out_of_bounds(self):
        self._login()
        resp = self.client.post('/api/reviews/', {'rating': 6, 'comment': 'Too much', 'review_type': 'business'})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_tenant_not_in_response(self):
        self._login()
        self.client.post('/api/reviews/', {'rating': 5, 'comment': 'Perfect', 'review_type': 'business'})
        resp = self.client.get('/api/reviews/')
        for r in resp.data['results']:
            self.assertNotIn('tenant', r)
