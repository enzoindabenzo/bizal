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
        Review.objects.create(tenant=self.t1, user=self.u1, rating=5, comment='Great!', review_type='business', is_approved=True)
        Review.objects.create(tenant=self.t2, user=self.u2, rating=4, comment='Good!', review_type='business', is_approved=True)

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
        resp = self.client.post('/api/reviews/', {'rating': 5, 'comment': 'Perfect', 'review_type': 'business'})
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertNotIn('tenant', resp.data)

    def test_new_review_is_unapproved_by_default(self):
        self._login()
        resp = self.client.post('/api/reviews/', {'rating': 5, 'comment': 'Pending check', 'review_type': 'business'})
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        review = Review.objects.get(comment='Pending check')
        self.assertFalse(review.is_approved)
        # shouldn't show up in the public list yet
        public = self.client.get('/api/reviews/')
        self.assertNotIn('Pending check', [r['comment'] for r in public.data['results']])

    def test_owner_can_approve_pending_review(self):
        owner = make_user('owner@myshop.com', self.tenant, role='owner')
        review = Review.objects.create(tenant=self.tenant, user=self.user, rating=5, comment='Awaiting mod', review_type='business')
        self.assertFalse(review.is_approved)
        client = APIClient()
        client.defaults['HTTP_HOST'] = 'myshop.bizal.al'
        client.force_authenticate(user=owner)
        resp = client.patch(f'/api/reviews/{review.id}/moderate/', {'is_approved': True}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        review.refresh_from_db()
        self.assertTrue(review.is_approved)

    def test_delete_blocked_when_plan_lacks_reviews_feature(self):
        """
        Regression test: ReviewDeleteView must be gated on
        HasTenantFeature('reviews') like ReviewManageListView and
        ReviewModerateView are. Previously an owner on a plan without the
        'reviews' feature could still DELETE reviews even though they
        couldn't list or moderate them.

        Every current plan actually grants 'reviews' (see PLAN_FEATURES —
        reviews are available Starter through Enterprise), so there's no
        real plan left to exercise the "lacks the feature" case through
        plan choice alone. Simulate it directly via a superadmin-style
        TenantFeature override instead, which tests the gate itself rather
        than depending on today's plan matrix.
        """
        from tenants.models import TenantFeature
        starter_tenant = make_tenant('starterbiz')
        owner = make_user('owner@starterbiz.com', starter_tenant, role='owner')
        TenantFeature.objects.update_or_create(
            tenant=starter_tenant, key='reviews',
            defaults={'value': 'False', 'is_custom_grant': True},
        )
        review = Review.objects.create(
            tenant=starter_tenant, user=owner, rating=5,
            comment='Should not be deletable', review_type='business', is_approved=True,
        )
        client = APIClient()
        client.defaults['HTTP_HOST'] = 'starterbiz.bizal.al'
        client.force_authenticate(user=owner)
        resp = client.delete(f'/api/reviews/{review.id}/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Review.objects.filter(pk=review.pk).exists())

    def test_delete_allowed_when_plan_has_reviews_feature(self):
        """Sanity check: delete still works normally on a plan with 'reviews' enabled (e.g. Pro)."""
        owner = make_user('owner2@myshop.com', self.tenant, role='owner')
        review = Review.objects.create(
            tenant=self.tenant, user=self.user, rating=5,
            comment='Deletable', review_type='business', is_approved=True,
        )
        client = APIClient()
        client.defaults['HTTP_HOST'] = 'myshop.bizal.al'
        client.force_authenticate(user=owner)
        resp = client.delete(f'/api/reviews/{review.id}/')
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Review.objects.filter(pk=review.pk).exists())
