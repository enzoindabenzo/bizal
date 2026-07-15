from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from accounts.models import User
from tenants.models import Tenant
from .models import StorefrontPage, HeroSlide, PageSection


class StorefrontTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(
            name='Test Biz', slug='testbiz', business_type='restaurant', plan='pro',
            is_active=True,
        )
        self.owner = User.objects.create_user(
            email='owner@testbiz.com', password='pass1234', tenant=self.tenant, role='owner',
        )
        self.client.defaults['HTTP_HOST'] = 'testbiz.bizal.al'
        StorefrontPage.objects.create(
            tenant=self.tenant, slug='about', title='About Us',
            body='<p>We are great.</p>', is_published=True,
        )
        StorefrontPage.objects.create(
            tenant=self.tenant, slug='draft-page', title='Draft',
            body='<p>Hidden.</p>', is_published=False,
        )

    def test_public_page_list_excludes_drafts(self):
        resp = self.client.get('/api/storefront/pages/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        slugs = [p['slug'] for p in resp.data['results']]
        self.assertIn('about', slugs)
        self.assertNotIn('draft-page', slugs)

    def test_public_page_detail_by_slug(self):
        resp = self.client.get('/api/storefront/pages/about/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['title'], 'About Us')

    def test_owner_can_create_page(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.post('/api/storefront/manage/pages/', {
            'slug': 'faq', 'title': 'FAQ', 'body': '<p>Q&A</p>', 'order': 1,
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_anonymous_cannot_manage_pages(self):
        resp = self.client.post('/api/storefront/manage/pages/', {
            'slug': 'hack', 'title': 'Hacked', 'body': 'lol',
        })
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


class StorefrontPageManageTest(TestCase):
    """Update/delete and cross-tenant scoping for the manage endpoints."""

    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(
            name='Manage Biz', slug='managebiz', business_type='restaurant',
            plan='pro', is_active=True,
        )
        self.other_tenant = Tenant.objects.create(
            name='Other Biz', slug='otherbiz', business_type='gym',
            plan='pro', is_active=True,
        )
        self.owner = User.objects.create_user(
            email='owner@managebiz.com', password='pass1234',
            tenant=self.tenant, role='owner',
        )
        self.client.defaults['HTTP_HOST'] = 'managebiz.bizal.al'
        self.client.force_authenticate(user=self.owner)
        self.page = StorefrontPage.objects.create(
            tenant=self.tenant, slug='services', title='Our Services',
            body='<p>We offer great services.</p>', is_published=True,
        )

    def test_owner_can_update_page(self):
        resp = self.client.patch(
            f'/api/storefront/manage/pages/{self.page.pk}/',
            {'title': 'Updated Title'},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.page.refresh_from_db()
        self.assertEqual(self.page.title, 'Updated Title')

    def test_owner_can_delete_page(self):
        resp = self.client.delete(f'/api/storefront/manage/pages/{self.page.pk}/')
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(StorefrontPage.objects.filter(pk=self.page.pk).exists())

    def test_duplicate_slug_returns_clean_400_not_500(self):
        """Creating a second page with a slug already used by this tenant
        must be a validation error, not an unhandled IntegrityError."""
        resp = self.client.post('/api/storefront/manage/pages/', {
            'slug': 'services', 'title': 'Duplicate', 'body': 'x',
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('slug', resp.data)
        self.assertEqual(
            StorefrontPage.objects.filter(tenant=self.tenant, slug='services').count(), 1,
        )

    def test_editing_page_keeping_its_own_slug_still_works(self):
        """Saving a page without changing its slug must not trip the
        duplicate-slug check against itself."""
        resp = self.client.patch(
            f'/api/storefront/manage/pages/{self.page.pk}/',
            {'slug': 'services', 'title': 'Services Renamed'},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.page.refresh_from_db()
        self.assertEqual(self.page.title, 'Services Renamed')

    def test_manage_list_includes_drafts(self):
        """The manage endpoint (owner-only) must return both published and draft pages."""
        StorefrontPage.objects.create(
            tenant=self.tenant, slug='hidden', title='Hidden Draft',
            body='<p>Draft.</p>', is_published=False,
        )
        resp = self.client.get('/api/storefront/manage/pages/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        slugs = [p['slug'] for p in resp.data['results']]
        self.assertIn('services', slugs)
        self.assertIn('hidden', slugs)

    def test_cross_tenant_page_update_returns_404(self):
        other_page = StorefrontPage.objects.create(
            tenant=self.other_tenant, slug='about', title='About',
            body='<p>Other tenant.</p>', is_published=True,
        )
        resp = self.client.patch(
            f'/api/storefront/manage/pages/{other_page.pk}/',
            {'title': 'Hacked'},
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        other_page.refresh_from_db()
        self.assertEqual(other_page.title, 'About')  # unchanged

    def test_customer_cannot_manage_pages(self):
        customer = User.objects.create_user(
            email='cust@managebiz.com', password='pass1234',
            tenant=self.tenant, role='customer',
        )
        self.client.force_authenticate(user=customer)
        resp = self.client.post('/api/storefront/manage/pages/', {
            'slug': 'hack', 'title': 'Hack', 'body': 'x',
        })
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


class HeroSlideTest(TestCase):
    """Public listing and owner management of hero slides."""

    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(
            name='Hero Biz', slug='herobiz', business_type='restaurant',
            plan='pro', is_active=True,
        )
        self.owner = User.objects.create_user(
            email='owner@herobiz.com', password='pass1234',
            tenant=self.tenant, role='owner',
        )
        self.client.defaults['HTTP_HOST'] = 'herobiz.bizal.al'
        self.slide = HeroSlide.objects.create(
            tenant=self.tenant, title='Welcome', subtitle='Best in town',
            cta_label='Book Now', cta_url='/book/', is_active=True, order=0,
        )
        HeroSlide.objects.create(
            tenant=self.tenant, title='Hidden', is_active=False, order=1,
        )

    def test_public_hero_list_excludes_inactive(self):
        resp = self.client.get('/api/storefront/hero/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        slides = resp.data['results'] if isinstance(resp.data, dict) else resp.data
        titles = [s['title'] for s in slides]
        self.assertIn('Welcome', titles)
        self.assertNotIn('Hidden', titles)

    def test_owner_can_create_hero_slide(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.post('/api/storefront/manage/hero/', {
            'title': 'New Slide', 'subtitle': 'Subtitle', 'is_active': True, 'order': 2,
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['title'], 'New Slide')

    def test_owner_can_update_hero_slide(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.patch(
            f'/api/storefront/manage/hero/{self.slide.pk}/',
            {'title': 'Updated Slide'},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.slide.refresh_from_db()
        self.assertEqual(self.slide.title, 'Updated Slide')

    def test_owner_can_delete_hero_slide(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.delete(f'/api/storefront/manage/hero/{self.slide.pk}/')
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(HeroSlide.objects.filter(pk=self.slide.pk).exists())

    def test_anonymous_cannot_manage_hero_slides(self):
        resp = self.client.post('/api/storefront/manage/hero/', {
            'title': 'Hack', 'is_active': True,
        })
        self.assertIn(resp.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_cross_tenant_hero_slides_not_visible(self):
        other_tenant = Tenant.objects.create(
            name='Other Hero', slug='otherhero', business_type='gym',
            plan='pro', is_active=True,
        )
        HeroSlide.objects.create(
            tenant=other_tenant, title='Other Slide', is_active=True, order=0,
        )
        resp = self.client.get('/api/storefront/hero/')
        slides = resp.data['results'] if isinstance(resp.data, dict) else resp.data
        titles = [s['title'] for s in slides]
        self.assertNotIn('Other Slide', titles)


class PageSectionTests(TestCase):
    """Regression coverage for the tenant-admin 'page sections' builder:
    locked rows auto-seed per page, can be hidden/reordered but never
    deleted, while custom rows support full CRUD."""

    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(
            name='Test Biz', slug='testbiz', business_type='restaurant', plan='pro',
            is_active=True,
        )
        self.owner = User.objects.create_user(
            email='owner@testbiz.com', password='pass1234', tenant=self.tenant, role='owner',
        )
        self.client.defaults['HTTP_HOST'] = 'testbiz.bizal.al'
        self.client.force_authenticate(user=self.owner)

    def test_locked_sections_seed_on_first_request(self):
        resp = self.client.get('/api/storefront/manage/sections/?page=overview')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        lock_keys = {row['section_type'] for row in resp.data}
        self.assertIn('locked', lock_keys)
        titles = {row['title'] for row in resp.data}
        self.assertIn('Kontakti', titles)
        self.assertNotIn('About', titles)  # 'about' deliberately removed from Overview

    def test_seeding_is_idempotent(self):
        self.client.get('/api/storefront/manage/sections/?page=services')
        resp = self.client.get('/api/storefront/manage/sections/?page=services')
        self.assertEqual(len(resp.data), 1)  # only the one 'grid' locked row, not duplicated

    def test_custom_page_gets_body_locked_section(self):
        resp = self.client.get('/api/storefront/manage/sections/?page=page:about')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 1)
        self.assertTrue(resp.data[0]['locked'])

    def test_owner_can_add_custom_section(self):
        resp = self.client.post('/api/storefront/manage/sections/', {
            'page': 'overview', 'section_type': 'text', 'title': 'Extra', 'body': 'Hello',
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertFalse(resp.data['locked'])

    def test_locked_section_cannot_be_deleted(self):
        self.client.get('/api/storefront/manage/sections/?page=services')
        locked = PageSection.objects.get(tenant=self.tenant, page_key='services', lock_key='grid')
        resp = self.client.delete(f'/api/storefront/manage/sections/{locked.id}/')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(PageSection.objects.filter(id=locked.id).exists())

    def test_locked_section_can_be_hidden_and_reordered(self):
        self.client.get('/api/storefront/manage/sections/?page=services')
        locked = PageSection.objects.get(tenant=self.tenant, page_key='services', lock_key='grid')
        resp = self.client.patch(f'/api/storefront/manage/sections/{locked.id}/', {'hidden': True, 'order': 3})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        locked.refresh_from_db()
        self.assertTrue(locked.hidden)
        self.assertEqual(locked.order, 3)

    def test_custom_section_can_be_deleted(self):
        create = self.client.post('/api/storefront/manage/sections/', {
            'page': 'menu', 'section_type': 'text', 'title': 'Promo',
        })
        resp = self.client.delete(f"/api/storefront/manage/sections/{create.data['id']}/")
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)

    def test_anonymous_cannot_manage_sections(self):
        self.client.force_authenticate(user=None)
        resp = self.client.get('/api/storefront/manage/sections/?page=overview')
        self.assertIn(resp.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))


class PageSectionPublicListTests(TestCase):
    """Regression coverage for the public read endpoint the storefront
    (index.html) actually renders from. This is the piece that was
    missing entirely: the admin builder could save hide/reorder/custom
    block changes, but nothing on the public site ever read them back."""

    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(
            name='Test Biz', slug='testbiz', business_type='restaurant', plan='pro',
            is_active=True,
        )
        self.owner = User.objects.create_user(
            email='owner@testbiz.com', password='pass1234', tenant=self.tenant, role='owner',
        )
        self.client.defaults['HTTP_HOST'] = 'testbiz.bizal.al'

    def test_anonymous_can_read_public_sections(self):
        self.client.force_authenticate(user=self.owner)
        self.client.get('/api/storefront/manage/sections/?page=services')
        self.client.force_authenticate(user=None)
        resp = self.client.get('/api/storefront/sections/?page=services')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 1)
        self.assertTrue(resp.data[0]['locked'])

    def test_hidden_locked_section_excluded_from_public_list(self):
        self.client.force_authenticate(user=self.owner)
        self.client.get('/api/storefront/manage/sections/?page=services')
        locked = PageSection.objects.get(tenant=self.tenant, page_key='services', lock_key='grid')
        self.client.patch(f'/api/storefront/manage/sections/{locked.id}/', {'hidden': True})
        self.client.force_authenticate(user=None)
        resp = self.client.get('/api/storefront/sections/?page=services')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 0)

    def test_custom_section_appears_in_public_list(self):
        self.client.force_authenticate(user=self.owner)
        self.client.post('/api/storefront/manage/sections/', {
            'page': 'services', 'section_type': 'text', 'title': 'Promo', 'body': 'Save 10%',
        })
        self.client.force_authenticate(user=None)
        resp = self.client.get('/api/storefront/sections/?page=services')
        titles = {row['title'] for row in resp.data}
        self.assertIn('Promo', titles)

    def test_never_opened_builder_returns_empty_list(self):
        # No admin request has ever hit manage/sections/ for this tenant+page,
        # so no rows (locked or custom) exist yet. Public list must come back
        # empty rather than erroring -- the frontend treats empty as "leave
        # this page's default markup untouched".
        resp = self.client.get('/api/storefront/sections/?page=services')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 0)

    def test_missing_page_param_returns_empty_list_not_error(self):
        resp = self.client.get('/api/storefront/sections/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 0)

    def test_public_list_is_cross_tenant_isolated(self):
        other = Tenant.objects.create(
            name='Other Biz', slug='otherbiz', business_type='restaurant', plan='pro',
            is_active=True,
        )
        other_owner = User.objects.create_user(
            email='owner@otherbiz.com', password='pass1234', tenant=other, role='owner',
        )
        other_client = APIClient()
        other_client.defaults['HTTP_HOST'] = 'otherbiz.bizal.al'
        other_client.force_authenticate(user=other_owner)
        other_client.post('/api/storefront/manage/sections/', {
            'page': 'services', 'section_type': 'text', 'title': 'Only For Other Biz',
        })
        resp = self.client.get('/api/storefront/sections/?page=services')
        titles = {row['title'] for row in resp.data}
        self.assertNotIn('Only For Other Biz', titles)
