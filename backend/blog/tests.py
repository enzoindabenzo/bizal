from django.test import TestCase, override_settings
from django.utils.text import slugify
from rest_framework.test import APIClient
from rest_framework import status
from accounts.models import User
from tenants.models import Tenant
from .models import BlogPost, BlogTag, STATUS_PUBLISHED, STATUS_DRAFT


def make_tenant(slug, plan='pro'):
    return Tenant.objects.create(
        name=slug.title(), slug=slug, plan=plan,
        is_active=True, business_type='restaurant',
    )


def make_user(email, tenant, role='owner'):
    return User.objects.create_user(
        email=email, password='pass1234', tenant=tenant, role=role,
    )


def make_post(tenant, title='Test Post', published=True, author=None):
    return BlogPost.objects.create(
        tenant=tenant,
        title=title,
        slug=slugify(title),
        body='Some body content.',
        status=STATUS_PUBLISHED if published else STATUS_DRAFT,
        author=author,
    )


# ── Public read ───────────────────────────────────────────────────────────────

class BlogPublicReadTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('blogbiz')
        self.other_tenant = make_tenant('otherblogbiz')
        self.client.defaults['HTTP_HOST'] = 'blogbiz.bizal.al'

        self.pub_post = make_post(self.tenant, 'Published Post')
        self.draft_post = make_post(self.tenant, 'Draft Post', published=False)
        make_post(self.other_tenant, 'Other Tenant Post')

    def test_public_list_shows_only_published(self):
        resp = self.client.get('/api/blog/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        titles = [p['title'] for p in ((resp.data['results'] if isinstance(resp.data, dict) else resp.data))]
        self.assertIn('Published Post', titles)
        self.assertNotIn('Draft Post', titles)

    def test_public_list_excludes_other_tenant(self):
        resp = self.client.get('/api/blog/')
        titles = [p['title'] for p in ((resp.data['results'] if isinstance(resp.data, dict) else resp.data))]
        self.assertNotIn('Other Tenant Post', titles)

    def test_public_detail_by_slug(self):
        resp = self.client.get(f'/api/blog/{self.pub_post.slug}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['title'], 'Published Post')

    def test_draft_not_accessible_publicly(self):
        resp = self.client.get(f'/api/blog/{self.draft_post.slug}/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_detail_increments_view_count(self):
        initial = self.pub_post.view_count
        self.client.get(f'/api/blog/{self.pub_post.slug}/')
        self.pub_post.refresh_from_db()
        self.assertEqual(self.pub_post.view_count, initial + 1)

    @override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
    def test_spoofed_leftmost_xff_does_not_bypass_view_count_dedup(self):
        """
        Regression: the per-IP hourly view-count dedup used to trust the
        leftmost X-Forwarded-For entry, which is set by the client itself
        and fully spoofable. A bot sending a fresh fake leftmost IP on every
        request could bypass the dedup cap entirely. Our nginx (the only
        public entry point) appends the real client IP as the rightmost
        entry, so that's the one a client can't forge — the dedup must key
        off that entry instead.

        The dedup cache is a no-op DummyCache in the test settings, so this
        test overrides it with a real (in-memory) cache backend to actually
        exercise the dedup logic.
        """
        initial = self.pub_post.view_count
        for i in range(3):
            self.client.get(
                f'/api/blog/{self.pub_post.slug}/',
                HTTP_X_FORWARDED_FOR=f'10.0.0.{i}, 203.0.113.9',
            )
        self.pub_post.refresh_from_db()
        # All three requests share the same trusted (rightmost) IP, so only
        # the first should have counted.
        self.assertEqual(self.pub_post.view_count, initial + 1)

    def test_filter_by_tag(self):
        tag = BlogTag.objects.create(tenant=self.tenant, name='Food', slug='food')
        self.pub_post.tags.add(tag)
        resp = self.client.get('/api/blog/?tag=food')
        titles = [p['title'] for p in ((resp.data['results'] if isinstance(resp.data, dict) else resp.data))]
        self.assertIn('Published Post', titles)

    def test_tags_endpoint(self):
        BlogTag.objects.create(tenant=self.tenant, name='Events', slug='events')
        resp = self.client.get('/api/blog/tags/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len((resp.data['results'] if isinstance(resp.data, dict) else resp.data)), 1)


# ── Owner write (manage) ──────────────────────────────────────────────────────

class BlogOwnerWriteTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        # enterprise plan has blog=True; pro+restaurant does not.
        self.tenant = make_tenant('writeblog', plan='enterprise')
        self.owner = make_user('owner@writeblog.com', self.tenant)
        self.customer = make_user('cust@writeblog.com', self.tenant, 'customer')
        self.client.defaults['HTTP_HOST'] = 'writeblog.bizal.al'

    def test_owner_can_create_post(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.post('/api/blog/manage/', {
            'title': 'New Article',
            'slug': 'new-article',
            'body': 'Content here.',
            'excerpt': 'Short excerpt.',
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(BlogPost.objects.filter(
            tenant=self.tenant, title='New Article'
        ).exists())

    def test_owner_manage_list_includes_drafts(self):
        make_post(self.tenant, 'Hidden Draft', published=False)
        make_post(self.tenant, 'Live Post', published=True)
        self.client.force_authenticate(user=self.owner)
        resp = self.client.get('/api/blog/manage/')
        titles = [p['title'] for p in ((resp.data['results'] if isinstance(resp.data, dict) else resp.data))]
        self.assertIn('Hidden Draft', titles)
        self.assertIn('Live Post', titles)

    def test_owner_can_update_post(self):
        post = make_post(self.tenant, 'Old Title')
        self.client.force_authenticate(user=self.owner)
        resp = self.client.patch(f'/api/blog/manage/{post.pk}/', {'title': 'Updated Title'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        post.refresh_from_db()
        self.assertEqual(post.title, 'Updated Title')

    def test_owner_can_delete_post(self):
        post = make_post(self.tenant, 'Delete Me')
        self.client.force_authenticate(user=self.owner)
        resp = self.client.delete(f'/api/blog/manage/{post.pk}/')
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(BlogPost.objects.filter(pk=post.pk).exists())

    def test_customer_cannot_create_post(self):
        self.client.force_authenticate(user=self.customer)
        resp = self.client.post('/api/blog/manage/', {
            'title': 'Sneaky Post', 'slug': 'sneaky', 'body': 'x',
        })
        self.assertIn(resp.status_code, [
            status.HTTP_403_FORBIDDEN, status.HTTP_401_UNAUTHORIZED,
        ])

    def test_wrong_tenant_cannot_delete(self):
        post = make_post(self.tenant, 'Protected')
        other_tenant = make_tenant('wrongblog')
        other_owner = make_user('o@wrongblog.com', other_tenant)
        self.client.force_authenticate(user=other_owner)
        resp = self.client.delete(f'/api/blog/manage/{post.pk}/')
        self.assertIn(resp.status_code, [
            status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND,
        ])
