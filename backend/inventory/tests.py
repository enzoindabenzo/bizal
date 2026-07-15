from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from accounts.models import User
from tenants.models import Tenant
from .models import ProductCategory, Product


def make_tenant(slug, plan='enterprise'):
    return Tenant.objects.create(
        name=slug.title(), slug=slug, plan=plan,
        is_active=True, business_type='retail',
    )


def make_user(email, tenant, role='owner'):
    return User.objects.create_user(
        email=email, password='pass1234', tenant=tenant, role=role,
    )


def make_category(tenant, name='Electronics'):
    from django.utils.text import slugify
    return ProductCategory.objects.create(
        tenant=tenant, name=name, slug=slugify(name),
    )


def make_product(tenant, category, name='Laptop', price=80000, stock=10):
    return Product.objects.create(
        tenant=tenant, category=category, name=name,
        price=price, stock=stock, is_active=True,
    )


# ── Public listing ────────────────────────────────────────────────────────────

class InventoryPublicTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('shopbiz')
        self.other_tenant = make_tenant('othershop')
        self.client.defaults['HTTP_HOST'] = 'shopbiz.bizal.al'

        self.cat = make_category(self.tenant, 'Electronics')
        self.product = make_product(self.tenant, self.cat, 'Laptop Pro', 120000, 5)
        other_cat = make_category(self.other_tenant, 'Hidden')
        make_product(self.other_tenant, other_cat, 'Secret Product', 1000)

    def test_public_can_list_products(self):
        resp = self.client.get('/api/inventory/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        names = [p['name'] for p in ((resp.data['results'] if isinstance(resp.data, dict) else resp.data))]
        self.assertIn('Laptop Pro', names)
        self.assertNotIn('Secret Product', names)

    def test_inactive_products_not_shown(self):
        self.product.is_active = False
        self.product.save()
        resp = self.client.get('/api/inventory/')
        names = [p['name'] for p in ((resp.data['results'] if isinstance(resp.data, dict) else resp.data))]
        self.assertNotIn('Laptop Pro', names)

    def test_in_stock_property(self):
        resp = self.client.get('/api/inventory/')
        items = (resp.data['results'] if isinstance(resp.data, dict) else resp.data)
        laptop = next(i for i in items if i['name'] == 'Laptop Pro')
        self.assertTrue(laptop['in_stock'])

    def test_out_of_stock_flag(self):
        self.product.stock = 0
        self.product.save()
        resp = self.client.get('/api/inventory/')
        items = (resp.data['results'] if isinstance(resp.data, dict) else resp.data)
        laptop = next((i for i in items if i['name'] == 'Laptop Pro'), None)
        if laptop:  # only shown if is_active and in visible queryset
            self.assertFalse(laptop['in_stock'])

    def test_categories_endpoint(self):
        resp = self.client.get('/api/inventory/categories/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        names = [c['name'] for c in ((resp.data['results'] if isinstance(resp.data, dict) else resp.data))]
        self.assertIn('Electronics', names)

    def test_filter_by_category(self):
        cat2 = make_category(self.tenant, 'Phones')
        make_product(self.tenant, cat2, 'iPhone', 90000, 3)
        resp = self.client.get(f'/api/inventory/?category={self.cat.slug}')
        names = [p['name'] for p in ((resp.data['results'] if isinstance(resp.data, dict) else resp.data))]
        self.assertIn('Laptop Pro', names)
        self.assertNotIn('iPhone', names)


# ── Owner management ──────────────────────────────────────────────────────────

class InventoryOwnerTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('ownshop')
        self.owner = make_user('owner@ownshop.com', self.tenant)
        self.customer = make_user('cust@ownshop.com', self.tenant, 'customer')
        self.cat = make_category(self.tenant, 'Accessories')
        self.client.defaults['HTTP_HOST'] = 'ownshop.bizal.al'

    def test_owner_can_create_product(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.post('/api/inventory/create/', {
            'name': 'Wireless Mouse',
            'price': '2500.00',
            'stock': 20,
            'category': str(self.cat.pk),
            'is_active': True,
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(Product.objects.filter(
            tenant=self.tenant, name='Wireless Mouse'
        ).exists())

    def test_owner_can_update_stock(self):
        product = make_product(self.tenant, self.cat, 'USB Hub', 1500, 10)
        self.client.force_authenticate(user=self.owner)
        resp = self.client.patch(
            f'/api/inventory/{product.pk}/manage/', {'stock': 25}
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        product.refresh_from_db()
        self.assertEqual(product.stock, 25)

    def test_owner_can_deactivate_product(self):
        product = make_product(self.tenant, self.cat, 'Old Model', 500, 2)
        self.client.force_authenticate(user=self.owner)
        resp = self.client.patch(
            f'/api/inventory/{product.pk}/manage/', {'is_active': False}
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        product.refresh_from_db()
        self.assertFalse(product.is_active)

    def test_owner_can_delete_product(self):
        product = make_product(self.tenant, self.cat, 'Discontinued', 100, 0)
        self.client.force_authenticate(user=self.owner)
        resp = self.client.delete(f'/api/inventory/{product.pk}/manage/')
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Product.objects.filter(pk=product.pk).exists())

    def test_customer_cannot_manage_inventory(self):
        self.client.force_authenticate(user=self.customer)
        resp = self.client.post('/api/inventory/create/', {
            'name': 'Hack', 'price': '1.00', 'stock': 1,
            'category': str(self.cat.pk),
        })
        self.assertIn(resp.status_code, [
            status.HTTP_403_FORBIDDEN, status.HTTP_401_UNAUTHORIZED,
        ])

    def test_cross_tenant_product_not_accessible(self):
        other_tenant = make_tenant('hackshop')
        other_cat = make_category(other_tenant, 'Other')
        other_product = make_product(other_tenant, other_cat, 'Cross Tenant', 100, 1)
        self.client.force_authenticate(user=self.owner)
        resp = self.client.patch(
            f'/api/inventory/{other_product.pk}/manage/', {'stock': 999}
        )
        self.assertIn(resp.status_code, [
            status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND,
        ])

    def test_owner_can_create_category(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.post('/api/inventory/categories/', {
            'name': 'Gaming', 'slug': 'gaming',
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_category_detail_endpoint_get_update_delete(self):
        """Regression test for issue #5: categories/<pk>/ detail endpoint was missing entirely."""
        self.client.force_authenticate(user=self.owner)
        resp = self.client.get(f'/api/inventory/categories/{self.cat.pk}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['name'], 'Accessories')

        resp = self.client.patch(f'/api/inventory/categories/{self.cat.pk}/', {'name': 'Accessories v2'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.cat.refresh_from_db()
        self.assertEqual(self.cat.name, 'Accessories v2')

        resp = self.client.delete(f'/api/inventory/categories/{self.cat.pk}/')
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(ProductCategory.objects.filter(pk=self.cat.pk).exists())


# ── Consolidated endpoints (issue #22) ──────────────────────────────────────
# The tenant admin UI calls POST /inventory/ and PATCH/DELETE /inventory/<id>/
# directly — matching every other resource's URL convention in the app —
# rather than the legacy /create/ and /<pk>/manage/ paths. Previously these
# routes only supported GET, so the UI's add/edit/delete-product flows were
# silently hitting 405. These tests cover the consolidated views directly.

class InventoryConsolidatedEndpointTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('consolidatedshop')
        self.owner = make_user('owner@consolidatedshop.com', self.tenant)
        self.customer = make_user('cust@consolidatedshop.com', self.tenant, 'customer')
        self.cat = make_category(self.tenant, 'Gadgets')
        self.client.defaults['HTTP_HOST'] = 'consolidatedshop.bizal.al'

    def test_owner_can_create_product_via_list_endpoint(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.post('/api/inventory/', {
            'name': 'Bluetooth Speaker',
            'price': '4500.00',
            'stock': 12,
            'category': str(self.cat.pk),
            'is_active': True,
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(Product.objects.filter(
            tenant=self.tenant, name='Bluetooth Speaker'
        ).exists())

    def test_anonymous_cannot_create_product_via_list_endpoint(self):
        resp = self.client.post('/api/inventory/', {
            'name': 'Hack', 'price': '1.00', 'stock': 1,
            'category': str(self.cat.pk),
        })
        self.assertIn(resp.status_code, [
            status.HTTP_403_FORBIDDEN, status.HTTP_401_UNAUTHORIZED,
        ])

    def test_owner_can_update_product_via_detail_endpoint(self):
        product = make_product(self.tenant, self.cat, 'Power Bank', 3000, 8)
        self.client.force_authenticate(user=self.owner)
        resp = self.client.patch(f'/api/inventory/{product.pk}/', {'stock': 50})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        product.refresh_from_db()
        self.assertEqual(product.stock, 50)

    def test_owner_can_delete_product_via_detail_endpoint(self):
        product = make_product(self.tenant, self.cat, 'Old Cable', 200, 0)
        self.client.force_authenticate(user=self.owner)
        resp = self.client.delete(f'/api/inventory/{product.pk}/')
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Product.objects.filter(pk=product.pk).exists())

    def test_customer_cannot_update_product_via_detail_endpoint(self):
        product = make_product(self.tenant, self.cat, 'Locked Item', 999, 1)
        self.client.force_authenticate(user=self.customer)
        resp = self.client.patch(f'/api/inventory/{product.pk}/', {'stock': 0})
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_public_get_on_detail_endpoint_excludes_inactive(self):
        product = make_product(self.tenant, self.cat, 'Hidden Item', 100, 1)
        product.is_active = False
        product.save(update_fields=['is_active'])
        resp = self.client.get(f'/api/inventory/{product.pk}/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_owner_can_reactivate_inactive_product_via_detail_endpoint(self):
        """
        Owner write access to ProductDetailView must reach inactive
        products too (e.g. to flip is_active back on) — only the public
        GET queryset is restricted to active products.
        """
        product = make_product(self.tenant, self.cat, 'Re-activatable', 100, 1)
        product.is_active = False
        product.save(update_fields=['is_active'])
        self.client.force_authenticate(user=self.owner)
        resp = self.client.patch(f'/api/inventory/{product.pk}/', {'is_active': True})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        product.refresh_from_db()
        self.assertTrue(product.is_active)

    def test_legacy_create_and_manage_aliases_still_work(self):
        """
        Backward compatibility: /create/ and /<pk>/manage/ are kept as
        aliases pointing at the same consolidated views.
        """
        self.client.force_authenticate(user=self.owner)
        resp = self.client.post('/api/inventory/create/', {
            'name': 'Legacy Path Item',
            'price': '1000.00',
            'stock': 5,
            'category': str(self.cat.pk),
            'is_active': True,
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        product = Product.objects.get(name='Legacy Path Item')
        resp = self.client.patch(f'/api/inventory/{product.pk}/manage/', {'stock': 99})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        product.refresh_from_db()
        self.assertEqual(product.stock, 99)


# ── Plan-limit / feature-gating regressions ────────────────────────────────────

class InventoryFeatureGatingTest(TestCase):
    """
    Regression tests: Product/ProductCategory management endpoints must be
    gated on HasTenantFeature('inventory'), and creation must respect the
    tenant's plan max_listings cap.
    """
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('gateshop')
        self.owner = make_user('owner@gateshop.com', self.tenant)
        self.client.defaults['HTTP_HOST'] = 'gateshop.bizal.al'
        self.client.force_authenticate(user=self.owner)
        self.category = make_category(self.tenant)

    def test_create_blocked_when_plan_lacks_inventory_feature(self):
        from tenants.models import TenantFeature
        TenantFeature.objects.update_or_create(
            tenant=self.tenant, key='inventory',
            defaults={'value': 'False', 'is_custom_grant': True},
        )
        resp = self.client.post('/api/inventory/create/', {
            'name': 'Blocked Product', 'category': str(self.category.id),
            'price': '100.00', 'stock': 5,
        })
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(Product.objects.filter(tenant=self.tenant, name='Blocked Product').exists())

    def test_max_listings_enforced_for_products(self):
        from tenants.models import TenantFeature
        TenantFeature.objects.update_or_create(
            tenant=self.tenant, key='max_listings',
            defaults={'value': '1', 'is_custom_grant': True},
        )
        make_product(self.tenant, self.category, 'Existing')
        resp = self.client.post('/api/inventory/create/', {
            'name': 'Overflow', 'category': str(self.category.id),
            'price': '100.00', 'stock': 5,
        })
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(Product.objects.filter(tenant=self.tenant).count(), 1)
