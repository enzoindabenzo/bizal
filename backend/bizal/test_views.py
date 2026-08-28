"""
Coverage for bizal/views.py — the SPA-shell / robots / sitemap / health
views. Tenant vs main-domain branches are triggered by setting HTTP_HOST
to a tenant subdomain (e.g. 'shop1.bizal.al') vs the bare main domain
('bizal.al'), matching the pattern used throughout tenants/tests.py.
"""
from unittest.mock import patch

from django.test import TestCase, override_settings

from tenants.models import Tenant


class HomeViewTests(TestCase):
    def test_main_domain_renders_landing_page(self):
        self.client.defaults['HTTP_HOST'] = 'bizal.al'
        resp = self.client.get('/')
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'main.html')

    def test_tenant_subdomain_renders_spa_shell(self):
        Tenant.objects.create(
            name='Shop One', slug='shop1', business_type='restaurant',
            is_active=True,
        )
        self.client.defaults['HTTP_HOST'] = 'shop1.bizal.al'
        resp = self.client.get('/')
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'index.html')


class TenantSpaCatchAllTests(TestCase):
    def test_main_domain_unrecognised_path_renders_main_shell(self):
        self.client.defaults['HTTP_HOST'] = 'bizal.al'
        resp = self.client.get('/some-unknown-path/')
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'main.html')

    def test_tenant_subdomain_unrecognised_path_renders_index(self):
        Tenant.objects.create(
            name='Shop Two', slug='shop2', business_type='restaurant',
            is_active=True,
        )
        self.client.defaults['HTTP_HOST'] = 'shop2.bizal.al'
        resp = self.client.get('/some/nested/path/')
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'index.html')


class AdminPanelViewTests(TestCase):
    def test_main_domain_redirects_to_django_admin(self):
        self.client.defaults['HTTP_HOST'] = 'bizal.al'
        resp = self.client.get('/admin/')
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, '/django-admin/')

    def test_tenant_subdomain_renders_tenant_admin_panel(self):
        Tenant.objects.create(
            name='Shop Three', slug='shop3', business_type='restaurant',
            is_active=True,
        )
        self.client.defaults['HTTP_HOST'] = 'shop3.bizal.al'
        resp = self.client.get('/admin/')
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'tenant_admin.html')


class OnboardingViewTests(TestCase):
    def test_onboarding_page_renders(self):
        self.client.defaults['HTTP_HOST'] = 'bizal.al'
        resp = self.client.get('/onboarding/')
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'onboarding.html')


class RobotsTxtTests(TestCase):
    def test_main_domain_blocks_admin_and_api(self):
        self.client.defaults['HTTP_HOST'] = 'bizal.al'
        resp = self.client.get('/robots.txt')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('Disallow: /api/', body)
        self.assertIn('Disallow: /django-admin/', body)
        self.assertIn('Sitemap:', body)

    def test_tenant_subdomain_points_at_frontend_base_url_sitemap(self):
        Tenant.objects.create(
            name='Robo Shop', slug='roboshop', business_type='restaurant',
            is_active=True,
        )
        self.client.defaults['HTTP_HOST'] = 'roboshop.bizal.al'
        resp = self.client.get('/robots.txt')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('Disallow: /onboarding/', body)
        self.assertNotIn('Disallow: /api/', body)  # only the main-domain branch blocks /api/
        self.assertIn('Sitemap:', body)

    @override_settings(FRONTEND_BASE_URL='')
    def test_tenant_subdomain_falls_back_to_request_host_when_no_frontend_base_url(self):
        Tenant.objects.create(
            name='Fallback Shop', slug='fallbackshop', business_type='restaurant',
            is_active=True,
        )
        self.client.defaults['HTTP_HOST'] = 'fallbackshop.bizal.al'
        resp = self.client.get('/robots.txt')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('Sitemap: http://fallbackshop.bizal.al/sitemap.xml', body)


class SitemapXmlTests(TestCase):
    def test_lists_active_marketplace_tenants(self):
        Tenant.objects.create(
            name='Listed Shop', slug='listed-shop', business_type='restaurant',
            is_active=True, listed_on_marketplace=True,
        )
        Tenant.objects.create(
            name='Unlisted Shop', slug='unlisted-shop', business_type='restaurant',
            is_active=True, listed_on_marketplace=False,
        )
        self.client.defaults['HTTP_HOST'] = 'bizal.al'
        resp = self.client.get('/sitemap.xml')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/xml')
        body = resp.content.decode()
        self.assertIn('listed-shop', body)
        self.assertNotIn('unlisted-shop.', body)

    @override_settings(FRONTEND_BASE_URL='')
    def test_falls_back_to_request_host_when_no_frontend_base_url(self):
        self.client.defaults['HTTP_HOST'] = 'bizal.al'
        resp = self.client.get('/sitemap.xml')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('http://bizal.al/', resp.content.decode())

    def test_tenant_query_failure_falls_back_to_empty_list(self):
        self.client.defaults['HTTP_HOST'] = 'bizal.al'
        with patch('tenants.models.Tenant.objects.filter', side_effect=Exception('db down')):
            resp = self.client.get('/sitemap.xml')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('<urlset', body)
        # No per-tenant <url> entries beyond the two static ones (/ and /marketplace/)
        self.assertEqual(body.count('<url>'), 2)


class HealthCheckTests(TestCase):
    def test_health_check_ok(self):
        resp = self.client.get('/health/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/json')
        self.assertIn('"status": "ok"', resp.content.decode())

    def test_health_check_degraded_on_db_failure(self):
        from django.db import OperationalError
        with patch('django.db.connection.cursor', side_effect=OperationalError('down')):
            resp = self.client.get('/health/')
        self.assertEqual(resp.status_code, 503)
        self.assertIn('"status": "degraded"', resp.content.decode())
