from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from accounts.models import User
from tenants.models import Tenant


class HeroSlideDuplicateOrderRegressionTest(TestCase):
    """Same pattern check as above, but for HeroSlide (openSlideModal uses
    the identical `data.order ?? 0` <- `slides.length` logic)."""
    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(
            name='Slide Biz', slug='slidebiz', business_type='restaurant',
            plan='pro', is_active=True,
        )
        self.owner = User.objects.create_user(
            email='owner@slidebiz.com', password='pass1234',
            tenant=self.tenant, role='owner',
        )
        self.client.defaults['HTTP_HOST'] = 'slidebiz.bizal.al'
        self.client.force_authenticate(user=self.owner)
        from .models import HeroSlide
        self.HeroSlide = HeroSlide
        self.a = HeroSlide.objects.create(tenant=self.tenant, title='A', order=0, is_active=True)
        self.b = HeroSlide.objects.create(tenant=self.tenant, title='B', order=1, is_active=True)
        self.c = HeroSlide.objects.create(tenant=self.tenant, title='C', order=2, is_active=True)

    def test_delete_then_add_duplicates_order(self):
        self.client.delete(f'/api/storefront/manage/hero/{self.b.pk}/')
        list_resp = self.client.get('/api/storefront/manage/hero/')
        count = len(list_resp.data['results'] if isinstance(list_resp.data, dict) else list_resp.data)
        self.assertEqual(count, 2)
        create_resp = self.client.post('/api/storefront/manage/hero/', {
            'title': 'D (new)', 'order': count,  # stale client value, must be ignored server-side
        })
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED)
        orders = list(self.HeroSlide.objects.filter(tenant=self.tenant).order_by('order').values_list('title', 'order'))
        print(f"\n[HERO REGRESSION CHECK] {orders}")
        all_orders = [o for _, o in orders]
        self.assertEqual(len(all_orders), len(set(all_orders)), "no two slides should share an order value")
        self.assertEqual(dict(orders)['D (new)'], 3)


class StorefrontPageDuplicateOrderRegressionTest(TestCase):
    """Same pattern check for StorefrontPage (openSfPageModal)."""
    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(
            name='Page Biz', slug='pagebiz', business_type='restaurant',
            plan='pro', is_active=True,
        )
        self.owner = User.objects.create_user(
            email='owner@pagebiz.com', password='pass1234',
            tenant=self.tenant, role='owner',
        )
        self.client.defaults['HTTP_HOST'] = 'pagebiz.bizal.al'
        self.client.force_authenticate(user=self.owner)
        from .models import StorefrontPage
        self.StorefrontPage = StorefrontPage
        self.a = StorefrontPage.objects.create(tenant=self.tenant, slug='a', title='A', body='x', order=0)
        self.b = StorefrontPage.objects.create(tenant=self.tenant, slug='b', title='B', body='x', order=1)
        self.c = StorefrontPage.objects.create(tenant=self.tenant, slug='c', title='C', body='x', order=2)

    def test_delete_then_add_duplicates_order(self):
        self.client.delete(f'/api/storefront/manage/pages/{self.b.pk}/')
        list_resp = self.client.get('/api/storefront/manage/pages/')
        count = len(list_resp.data['results'] if isinstance(list_resp.data, dict) else list_resp.data)
        self.assertEqual(count, 2)
        create_resp = self.client.post('/api/storefront/manage/pages/', {
            'title': 'D (new)', 'slug': 'd-new', 'body': 'x', 'order': count,  # stale client value, must be ignored
        })
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED)
        orders = list(self.StorefrontPage.objects.filter(tenant=self.tenant).order_by('order').values_list('title', 'order'))
        print(f"\n[PAGE REGRESSION CHECK] {orders}")
        all_orders = [o for _, o in orders]
        self.assertEqual(len(all_orders), len(set(all_orders)), "no two pages should share an order value")
        self.assertEqual(dict(orders)['D (new)'], 3)
