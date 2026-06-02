from django.test import TestCase, RequestFactory
from django.http import Http404
from .models import Tenant, PLAN_PRO, PLAN_ENTERPRISE, PLAN_STARTER
from .middleware import TenantMiddleware


def make_tenant(slug='test-biz', plan=PLAN_PRO, active=True, business_type='restaurant'):
    return Tenant.objects.create(
        name=slug.replace('-', ' ').title(),
        slug=slug, plan=plan,
        is_active=active,
        business_type=business_type
    )


class TenantModelTest(TestCase):
    def test_slug_auto_generated(self):
        t = Tenant.objects.create(name='My Restaurant', is_active=True, plan=PLAN_STARTER)
        self.assertEqual(t.slug, 'my-restaurant')

    def test_plan_defaults_applied_on_save(self):
        t = make_tenant(plan=PLAN_PRO)
        self.assertTrue(t.has_feature('analytics'))
        self.assertFalse(t.has_feature('blog'))

    def test_enterprise_has_all_features(self):
        t = make_tenant(plan=PLAN_ENTERPRISE)
        for feature in ('analytics', 'reviews', 'blog', 'payments', 'crm', 'csv_export'):
            self.assertTrue(t.has_feature(feature), f"Enterprise missing feature: {feature}")

    def test_starter_has_no_features(self):
        t = make_tenant(plan=PLAN_STARTER)
        for feature in ('analytics', 'reviews', 'blog', 'contact_form'):
            self.assertFalse(t.has_feature(feature), f"Starter should not have feature: {feature}")

    def test_plan_upgrade_reapplies_features(self):
        t = make_tenant(plan=PLAN_STARTER)
        self.assertFalse(t.has_feature('analytics'))
        t.plan = PLAN_PRO
        t.save()
        self.assertTrue(t.has_feature('analytics'))

    def test_str(self):
        t = make_tenant(slug='biz-test')
        self.assertIn('biz-test', str(t))


class TenantMiddlewareProductionTest(TestCase):
    """Tests subdomain resolution in production (bizal.al domain)."""

    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = TenantMiddleware(lambda r: r)
        self.tenant = make_tenant(slug='hertz', active=True)

    def test_production_subdomain_resolves_tenant(self):
        request = self.factory.get('/', HTTP_HOST='hertz.bizal.al')
        self.middleware(request)
        self.assertEqual(request.tenant, self.tenant)

    def test_production_main_domain_no_tenant(self):
        request = self.factory.get('/', HTTP_HOST='bizal.al')
        self.middleware(request)
        self.assertIsNone(request.tenant)

    def test_production_www_no_tenant(self):
        request = self.factory.get('/', HTTP_HOST='www.bizal.al')
        self.middleware(request)
        self.assertIsNone(request.tenant)

    def test_production_unknown_subdomain_404(self):
        request = self.factory.get('/', HTTP_HOST='unknown-biz.bizal.al')
        with self.assertRaises(Http404):
            self.middleware(request)

    def test_production_inactive_tenant_404(self):
        make_tenant(slug='inactive-biz', active=False)
        request = self.factory.get('/', HTTP_HOST='inactive-biz.bizal.al')
        with self.assertRaises(Http404):
            self.middleware(request)


class TenantMiddlewareDevPortTest(TestCase):
    """
    Tests port-based dev routing:
      localhost:8000 → main domain (no tenant)
      localhost:8001 + ?tenant=slug → tenant portal
    """

    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = TenantMiddleware(lambda r: r)
        self.tenant = make_tenant(slug='myshop', active=True)

    def test_port_8000_is_main_domain(self):
        request = self.factory.get('/', HTTP_HOST='localhost:8000')
        self.middleware(request)
        self.assertIsNone(request.tenant)

    def test_port_8001_with_slug_resolves_tenant(self):
        request = self.factory.get('/?tenant=myshop', HTTP_HOST='localhost:8001')
        self.middleware(request)
        self.assertEqual(request.tenant, self.tenant)

    def test_port_8001_without_slug_raises_404(self):
        request = self.factory.get('/', HTTP_HOST='localhost:8001')
        with self.assertRaises(Http404):
            self.middleware(request)

    def test_port_8001_unknown_slug_raises_404(self):
        request = self.factory.get('/?tenant=doesnotexist', HTTP_HOST='localhost:8001')
        with self.assertRaises(Http404):
            self.middleware(request)

    def test_port_8001_inactive_tenant_raises_404(self):
        make_tenant(slug='closed-shop', active=False)
        request = self.factory.get('/?tenant=closed-shop', HTTP_HOST='localhost:8001')
        with self.assertRaises(Http404):
            self.middleware(request)

    def test_127_0_0_1_port_8000_is_main_domain(self):
        request = self.factory.get('/', HTTP_HOST='127.0.0.1:8000')
        self.middleware(request)
        self.assertIsNone(request.tenant)

    def test_127_0_0_1_port_8001_with_slug(self):
        request = self.factory.get('/?tenant=myshop', HTTP_HOST='127.0.0.1:8001')
        self.middleware(request)
        self.assertEqual(request.tenant, self.tenant)

    def test_subdomain_localhost_still_works(self):
        """slug.localhost:8000 also resolves tenant (alternative dev method)."""
        request = self.factory.get('/', HTTP_HOST='myshop.localhost:8000')
        self.middleware(request)
        self.assertEqual(request.tenant, self.tenant)


class TenantIsolationTest(TestCase):
    def setUp(self):
        self.t1 = make_tenant(slug='shop-one', plan=PLAN_PRO)
        self.t2 = make_tenant(slug='shop-two', plan=PLAN_PRO)

    def test_tenants_have_different_ids(self):
        self.assertNotEqual(self.t1.id, self.t2.id)

    def test_feature_flags_are_independent(self):
        self.t1.plan = PLAN_ENTERPRISE
        self.t1.save()
        # t1 now has blog, t2 (still Pro) should not
        self.assertTrue(self.t1.has_feature('blog'))
        self.assertFalse(self.t2.has_feature('blog'))

    def test_features_dont_bleed_across_tenants(self):
        from .models import TenantFeature
        count_t1 = TenantFeature.objects.filter(tenant=self.t1).count()
        count_t2 = TenantFeature.objects.filter(tenant=self.t2).count()
        self.assertGreater(count_t1, 0)
        self.assertGreater(count_t2, 0)
        # No features shared between tenants
        shared = TenantFeature.objects.filter(tenant=self.t1).filter(tenant=self.t2)
        self.assertEqual(shared.count(), 0)
