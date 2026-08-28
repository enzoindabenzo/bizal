from django.test import TestCase

from rest_framework.test import APIClient

from rest_framework import status

from tenants.models import Tenant, PLAN_PRO

from accounts.models import User

from .models import Review

from tenants.models import Tenant

from reviews.models import Review

from reviews.platform_models import PlatformReview

from unittest.mock import patch

from .views import ReviewListCreateView

from .platform_models import PlatformReview


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


class ReviewAdminApproveReviewsTests(TestCase):
    def setUp(self):
        self.superadmin = User.objects.create_user(
            email='root-review@bizal.al', password='rootpass',
            is_superuser=True, is_staff=True,
        )
        self.client.force_login(self.superadmin)
        self.tenant = Tenant.objects.create(
            name='Review Co', slug='reviewco-admin', business_type='restaurant',
            plan='pro', is_active=True,
        )
        self.customer = User.objects.create_user(
            email='cust-review@example.com', password='pass1234', tenant=self.tenant, role='customer',
        )
        self.review = Review.objects.create(
            tenant=self.tenant, user=self.customer, review_type='business',
            rating=5, comment='Great!', is_approved=False,
        )

    def test_approve_reviews_action(self):
        resp = self.client.post('/django-admin/reviews/review/', {
            'action': 'approve_reviews',
            '_selected_action': [str(self.review.pk)],
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.review.refresh_from_db()
        self.assertTrue(self.review.is_approved)


class PlatformReviewAdminApproveReviewsTests(TestCase):
    def setUp(self):
        self.superadmin = User.objects.create_user(
            email='root-platreview@bizal.al', password='rootpass',
            is_superuser=True, is_staff=True,
        )
        self.client.force_login(self.superadmin)
        self.platform_review = PlatformReview.objects.create(
            reviewer_name='Dritan', business_name='Kafe X', rating=5,
            comment='Excellent platform', is_approved=False,
        )

    def test_approve_reviews_action(self):
        resp = self.client.post('/django-admin/reviews/platformreview/', {
            'action': 'approve_reviews',
            '_selected_action': [str(self.platform_review.pk)],
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.platform_review.refresh_from_db()
        self.assertTrue(self.platform_review.is_approved)
        self.assertIsNotNone(self.platform_review.approved_at)


class ReviewListLimitParamTests(TestCase):
    """Covers ReviewListCreateView.list()'s ?limit= fast-path (lines 31-40)."""

    def setUp(self):
        self.tenant = make_tenant('limitshop')
        self.user = make_user('u@limitshop.com', self.tenant)
        for i in range(5):
            Review.objects.create(
                tenant=self.tenant, user=self.user, rating=5,
                comment=f'Review {i}', review_type='business', is_approved=True,
            )
        self.client = APIClient()
        self.client.defaults['HTTP_HOST'] = 'limitshop.bizal.al'

    def test_valid_limit_returns_capped_unpaginated_list(self):
        resp = self.client.get('/api/reviews/', {'limit': 2})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 2)

    def test_limit_above_max_is_capped_at_100(self):
        resp = self.client.get('/api/reviews/', {'limit': 999999})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 5)  # only 5 exist, well under the cap

    def test_non_numeric_limit_falls_back_to_normal_pagination(self):
        resp = self.client.get('/api/reviews/', {'limit': 'abc'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        # falls through to the paginated response shape
        self.assertIn('results', resp.data)

    def test_negative_limit_falls_back_to_normal_pagination(self):
        # int('-1') succeeds but queryset[:-1] raises AssertionError (negative
        # slice indices unsupported), which is caught alongside ValueError.
        resp = self.client.get('/api/reviews/', {'limit': '-1'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('results', resp.data)


class ReviewListNonPaginatedFallbackTests(TestCase):
    """Covers ReviewListCreateView.list()'s non-paginated fallback (line 44).

    Under the app's real settings PAGE_SIZE is always a truthy 20, so
    PageNumberPagination.paginate_queryset() never actually returns None
    in normal request flow -- ?limit= is the only "unpaginated" path a
    real caller can reach, and that's covered above. This exercises the
    defensive fallback directly by forcing paginate_queryset() to return
    None, the same way it's exercised elsewhere in this codebase (e.g.
    staff/test_gaps2.py, accounts/test_final_gaps.py).
    """

    def setUp(self):
        self.tenant = make_tenant('fallbackshop')
        self.user = make_user('u@fallbackshop.com', self.tenant)
        Review.objects.create(
            tenant=self.tenant, user=self.user, rating=5,
            comment='Unpaginated review', review_type='business', is_approved=True,
        )
        self.client = APIClient()
        self.client.defaults['HTTP_HOST'] = 'fallbackshop.bizal.al'

    def test_list_falls_back_to_plain_list_when_pagination_disabled(self):
        with patch.object(ReviewListCreateView, 'paginate_queryset', return_value=None):
            resp = self.client.get('/api/reviews/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIsInstance(resp.data, list)
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]['comment'], 'Unpaginated review')


class ReviewCrossTenantCreateTests(TestCase):
    """Covers ReviewListCreateView.perform_create()'s cross-tenant guard (lines 56-57)."""

    def setUp(self):
        self.t1 = make_tenant('homebiz')
        self.t2 = make_tenant('otherbiz')

    def test_user_registered_elsewhere_cannot_review_this_tenant(self):
        user = make_user('u@homebiz.com', self.t1)
        client = APIClient()
        client.defaults['HTTP_HOST'] = 'otherbiz.bizal.al'
        client.force_authenticate(user=user)
        resp = client.post('/api/reviews/', {'rating': 5, 'comment': 'Sneaky', 'review_type': 'business'})
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(Review.objects.filter(comment='Sneaky').exists())

    def test_guest_user_with_no_home_tenant_can_review(self):
        guest = make_user('guest@nowhere.com', tenant=None)
        client = APIClient()
        client.defaults['HTTP_HOST'] = 'otherbiz.bizal.al'
        client.force_authenticate(user=guest)
        resp = client.post('/api/reviews/', {'rating': 5, 'comment': 'Guest review', 'review_type': 'business'})
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)


class ReviewDeleteOwnReviewTests(TestCase):
    """Covers the customer-only branch of ReviewDeleteView.get_queryset() (line 91)."""

    def setUp(self):
        self.tenant = make_tenant('delshop')
        self.owner_review_author = make_user('author@delshop.com', self.tenant)
        self.other_customer = make_user('other@delshop.com', self.tenant)
        self.review = Review.objects.create(
            tenant=self.tenant, user=self.owner_review_author, rating=5,
            comment='Mine', review_type='business', is_approved=True,
        )
        self.client = APIClient()
        self.client.defaults['HTTP_HOST'] = 'delshop.bizal.al'

    def test_customer_can_delete_own_review(self):
        self.client.force_authenticate(user=self.owner_review_author)
        resp = self.client.delete(f'/api/reviews/{self.review.id}/')
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Review.objects.filter(pk=self.review.pk).exists())

    def test_customer_cannot_delete_someone_elses_review(self):
        self.client.force_authenticate(user=self.other_customer)
        resp = self.client.delete(f'/api/reviews/{self.review.id}/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(Review.objects.filter(pk=self.review.pk).exists())


class ReviewManageListStatusFilterTests(TestCase):
    """Covers ReviewManageListView.get_queryset()'s ?status= filter (lines 104-110)."""

    def setUp(self):
        self.tenant = make_tenant('manageshop')
        self.owner = make_user('owner@manageshop.com', self.tenant, role='owner')
        self.customer = make_user('cust@manageshop.com', self.tenant)
        self.pending = Review.objects.create(
            tenant=self.tenant, user=self.customer, rating=3,
            comment='Pending one', review_type='business', is_approved=False,
        )
        self.approved = Review.objects.create(
            tenant=self.tenant, user=self.customer, rating=5,
            comment='Approved one', review_type='business', is_approved=True,
        )
        self.client = APIClient()
        self.client.defaults['HTTP_HOST'] = 'manageshop.bizal.al'
        self.client.force_authenticate(user=self.owner)

    def test_no_status_filter_returns_all(self):
        resp = self.client.get('/api/reviews/manage/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        comments = [r['comment'] for r in resp.data['results']]
        self.assertIn('Pending one', comments)
        self.assertIn('Approved one', comments)

    def test_status_pending_filters_to_unapproved_only(self):
        resp = self.client.get('/api/reviews/manage/', {'status': 'pending'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        comments = [r['comment'] for r in resp.data['results']]
        self.assertIn('Pending one', comments)
        self.assertNotIn('Approved one', comments)

    def test_status_approved_filters_to_approved_only(self):
        resp = self.client.get('/api/reviews/manage/', {'status': 'approved'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        comments = [r['comment'] for r in resp.data['results']]
        self.assertIn('Approved one', comments)
        self.assertNotIn('Pending one', comments)


def make_review(**kwargs):
    defaults = dict(
        reviewer_name='Ana K.', business_name='Kafe Studio', business_type='cafe',
        rating=5, comment='Platforma më ndryshoi biznesin krejtësisht, e rekomandoj!',
        is_approved=True,
    )
    defaults.update(kwargs)
    return PlatformReview.objects.create(**defaults)


class PlatformReviewListCreateTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_list_only_returns_approved(self):
        make_review(is_approved=True)
        make_review(is_approved=False, reviewer_name='Pending P.')
        resp = self.client.get('/api/platform-reviews/')
        self.assertEqual(resp.status_code, 200)
        data = resp.data['results'] if isinstance(resp.data, dict) else resp.data
        self.assertEqual(len(data), 1)

    def test_list_respects_limit_param(self):
        for i in range(5):
            make_review(reviewer_name=f'User {i}')
        resp = self.client.get('/api/platform-reviews/?limit=2')
        self.assertEqual(resp.status_code, 200)
        data = resp.data['results'] if isinstance(resp.data, dict) else resp.data
        self.assertEqual(len(data), 2)

    def test_list_limit_capped_at_100(self):
        for i in range(3):
            make_review(reviewer_name=f'Cap {i}')
        resp = self.client.get('/api/platform-reviews/?limit=999999')
        self.assertEqual(resp.status_code, 200)
        data = resp.data['results'] if isinstance(resp.data, dict) else resp.data
        self.assertEqual(len(data), 3)

    def test_list_invalid_limit_ignored(self):
        make_review()
        resp = self.client.get('/api/platform-reviews/?limit=notanumber')
        self.assertEqual(resp.status_code, 200)

    def test_create_review_anonymous(self):
        resp = self.client.post('/api/platform-reviews/', {
            'reviewer_name': 'Bes K.', 'business_name': 'Restorant Bes',
            'business_type': 'restaurant', 'rating': 5,
            'comment': 'Shumë i lehtë për t\'u përdorur dhe suport i shpejtë.',
        })
        self.assertEqual(resp.status_code, 201)
        review = PlatformReview.objects.get(reviewer_name='Bes K.')
        self.assertFalse(review.is_approved)
        self.assertIsNone(review.user)

    def test_create_review_authenticated_sets_user(self):
        user = User.objects.create_user(email='reviewer@test.com', password='pass1234', tenant=None)
        self.client.force_authenticate(user=user)
        resp = self.client.post('/api/platform-reviews/', {
            'reviewer_name': 'Loyal User', 'rating': 4,
            'comment': 'Funksionon shumë mirë për biznesin tim të vogël.',
        })
        self.assertEqual(resp.status_code, 201)
        review = PlatformReview.objects.get(reviewer_name='Loyal User')
        self.assertEqual(review.user, user)

    def test_create_review_short_comment_rejected(self):
        resp = self.client.post('/api/platform-reviews/', {
            'reviewer_name': 'Short C.', 'rating': 3, 'comment': 'too short',
        })
        self.assertEqual(resp.status_code, 400)

    def test_create_review_invalid_rating_rejected(self):
        resp = self.client.post('/api/platform-reviews/', {
            'reviewer_name': 'Bad R.', 'rating': 9, 'comment': 'A perfectly long enough comment here.',
        })
        self.assertEqual(resp.status_code, 400)

    def test_create_review_short_name_rejected(self):
        resp = self.client.post('/api/platform-reviews/', {
            'reviewer_name': 'A', 'rating': 5, 'comment': 'A perfectly long enough comment here.',
        })
        self.assertEqual(resp.status_code, 400)


class PlatformReviewSummaryTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_summary_no_reviews(self):
        resp = self.client.get('/api/platform-reviews/summary/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['average'], 0)
        self.assertEqual(resp.data['total'], 0)
        self.assertEqual(resp.data['distribution'], {str(i): 0 for i in range(1, 6)})

    def test_summary_aggregates_approved_only(self):
        make_review(rating=5, is_approved=True)
        make_review(rating=5, is_approved=True)
        make_review(rating=1, is_approved=True)
        make_review(rating=1, is_approved=False)  # excluded
        resp = self.client.get('/api/platform-reviews/summary/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['total'], 3)
        self.assertAlmostEqual(resp.data['average'], 3.7, places=1)
        self.assertEqual(resp.data['distribution']['5'], 2)
        self.assertEqual(resp.data['distribution']['1'], 1)
        self.assertEqual(resp.data['distribution']['3'], 0)


class PlatformReviewAdminTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            email='admin@bizal.al', password='pass1234', tenant=None,
            is_staff=True, is_superuser=True,
        )
        self.non_admin = User.objects.create_user(
            email='plain@bizal.al', password='pass1234', tenant=None,
        )

    def test_admin_list_requires_admin(self):
        resp = self.client.get('/api/platform-reviews/admin/')
        self.assertEqual(resp.status_code, 401)

    def test_admin_list_rejects_non_staff(self):
        self.client.force_authenticate(user=self.non_admin)
        resp = self.client.get('/api/platform-reviews/admin/')
        self.assertEqual(resp.status_code, 403)

    def test_admin_list_returns_all(self):
        make_review(is_approved=True)
        make_review(is_approved=False, reviewer_name='Pending')
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get('/api/platform-reviews/admin/')
        self.assertEqual(resp.status_code, 200)
        data = resp.data['results'] if isinstance(resp.data, dict) else resp.data
        self.assertEqual(len(data), 2)

    def test_admin_list_filters_pending(self):
        make_review(is_approved=True)
        make_review(is_approved=False, reviewer_name='Pending')
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get('/api/platform-reviews/admin/?status=pending')
        data = resp.data['results'] if isinstance(resp.data, dict) else resp.data
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['reviewer_name'], 'Pending')

    def test_admin_list_filters_approved(self):
        make_review(is_approved=True)
        make_review(is_approved=False, reviewer_name='Pending')
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get('/api/platform-reviews/admin/?status=approved')
        data = resp.data['results'] if isinstance(resp.data, dict) else resp.data
        self.assertEqual(len(data), 1)

    def test_approve_review(self):
        review = make_review(is_approved=False)
        self.client.force_authenticate(user=self.admin)
        resp = self.client.patch(f'/api/platform-reviews/admin/{review.pk}/', {'is_approved': True}, format='json')
        self.assertEqual(resp.status_code, 200)
        review.refresh_from_db()
        self.assertTrue(review.is_approved)
        self.assertIsNotNone(review.approved_at)

    def test_reject_review_clears_approved_at(self):
        from django.utils import timezone
        review = make_review(is_approved=True, approved_at=timezone.now())
        self.client.force_authenticate(user=self.admin)
        resp = self.client.patch(f'/api/platform-reviews/admin/{review.pk}/', {'is_approved': False}, format='json')
        self.assertEqual(resp.status_code, 200)
        review.refresh_from_db()
        self.assertFalse(review.is_approved)
        self.assertIsNone(review.approved_at)

    def test_approve_missing_field_rejected(self):
        review = make_review(is_approved=False)
        self.client.force_authenticate(user=self.admin)
        resp = self.client.patch(f'/api/platform-reviews/admin/{review.pk}/', {}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_approve_requires_admin(self):
        review = make_review(is_approved=False)
        resp = self.client.patch(f'/api/platform-reviews/admin/{review.pk}/', {'is_approved': True}, format='json')
        self.assertEqual(resp.status_code, 401)

    def test_approve_uses_integer_pk_routing(self):
        """
        Regression test for the routing bug: PlatformReview's pk is an
        integer (BigAutoField), so the endpoint must be reachable via a
        plain integer in the URL, not a UUID.
        """
        review = make_review(is_approved=False)
        self.assertIsInstance(review.pk, int)
        self.client.force_authenticate(user=self.admin)
        resp = self.client.patch(f'/api/platform-reviews/admin/{review.pk}/', {'is_approved': True}, format='json')
        self.assertEqual(resp.status_code, 200)
