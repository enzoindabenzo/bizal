from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from accounts.models import User
from tenants.models import Tenant
from .models import MenuCategory, MenuItem


def make_tenant(slug, plan='pro'):
    return Tenant.objects.create(
        name=slug.title(), slug=slug, plan=plan,
        is_active=True, business_type='restaurant',
    )


def make_user(email, tenant, role='owner'):
    return User.objects.create_user(
        email=email, password='pass1234', tenant=tenant, role=role,
    )


def make_category(tenant, name='Antipasta', order=0):
    return MenuCategory.objects.create(tenant=tenant, name=name, order=order)


def make_item(category, tenant, name='Bruschetta', price=350):
    return MenuItem.objects.create(
        tenant=tenant, category=category, name=name,
        price=price, is_available=True,
    )


# ── Public read ───────────────────────────────────────────────────────────────

class MenuPublicTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('restorant1')
        self.other_tenant = make_tenant('restorant2')
        self.client.defaults['HTTP_HOST'] = 'restorant1.bizal.al'

        self.cat = make_category(self.tenant, 'Antipasta')
        self.item = make_item(self.cat, self.tenant, 'Bruschetta', 350)
        other_cat = make_category(self.other_tenant, 'Pasta')
        make_item(other_cat, self.other_tenant, 'Spaghetti', 700)

    def test_public_can_list_categories_with_items(self):
        resp = self.client.get('/api/menu/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        names = [c['name'] for c in ((resp.data['results'] if isinstance(resp.data, dict) else resp.data))]
        self.assertIn('Antipasta', names)
        self.assertNotIn('Pasta', names)

    def test_category_includes_items(self):
        resp = self.client.get('/api/menu/')
        cats = (resp.data['results'] if isinstance(resp.data, dict) else resp.data)
        antip = next(c for c in cats if c['name'] == 'Antipasta')
        item_names = [i['name'] for i in antip['items']]
        self.assertIn('Bruschetta', item_names)

    def test_unavailable_items_not_shown_publicly(self):
        self.item.is_available = False
        self.item.save()
        resp = self.client.get('/api/menu/')
        cats = (resp.data['results'] if isinstance(resp.data, dict) else resp.data)
        antip = next((c for c in cats if c['name'] == 'Antipasta'), None)
        if antip:
            item_names = [i['name'] for i in antip['items']]
            self.assertNotIn('Bruschetta', item_names)

    def test_public_can_list_items_directly(self):
        resp = self.client.get('/api/menu/items/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        names = [i['name'] for i in ((resp.data['results'] if isinstance(resp.data, dict) else resp.data))]
        self.assertIn('Bruschetta', names)


# ── Owner management ──────────────────────────────────────────────────────────

class MenuOwnerTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('owneresto')
        self.owner = make_user('owner@owneresto.com', self.tenant)
        self.customer = make_user('cust@owneresto.com', self.tenant, 'customer')
        self.cat = make_category(self.tenant, 'Desserts')
        self.client.defaults['HTTP_HOST'] = 'owneresto.bizal.al'

    def test_owner_can_create_category(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.post('/api/menu/categories/', {
            'name': 'Cocktails', 'order': 5,
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(MenuCategory.objects.filter(
            tenant=self.tenant, name='Cocktails'
        ).exists())

    def test_owner_can_update_category(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.patch(
            f'/api/menu/categories/{self.cat.pk}/', {'name': 'Dolçe'}
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.cat.refresh_from_db()
        self.assertEqual(self.cat.name, 'Dolçe')

    def test_owner_can_delete_category(self):
        cat = make_category(self.tenant, 'Gone')
        self.client.force_authenticate(user=self.owner)
        resp = self.client.delete(f'/api/menu/categories/{cat.pk}/')
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)

    def test_owner_can_create_item(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.post('/api/menu/items/', {
            'category': str(self.cat.pk),
            'name': 'Tiramisu',
            'price': '600.00',
            'is_available': True,
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_owner_can_toggle_availability(self):
        item = make_item(self.cat, self.tenant, 'Chocolate Cake', 500)
        self.client.force_authenticate(user=self.owner)
        resp = self.client.patch(
            f'/api/menu/items/{item.pk}/', {'is_available': False}
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        item.refresh_from_db()
        self.assertFalse(item.is_available)

    def test_owner_can_delete_item(self):
        item = make_item(self.cat, self.tenant, 'Remove Me', 400)
        self.client.force_authenticate(user=self.owner)
        resp = self.client.delete(f'/api/menu/items/{item.pk}/')
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)

    def test_customer_cannot_modify_menu(self):
        self.client.force_authenticate(user=self.customer)
        resp = self.client.post('/api/menu/categories/', {'name': 'Hack', 'order': 0})
        self.assertIn(resp.status_code, [
            status.HTTP_403_FORBIDDEN, status.HTTP_401_UNAUTHORIZED,
        ])

    def test_cross_tenant_item_not_accessible(self):
        other_tenant = make_tenant('othermenu')
        other_cat = make_category(other_tenant, 'Foreign')
        other_item = make_item(other_cat, other_tenant, 'Foreign Item', 100)
        self.client.force_authenticate(user=self.owner)
        resp = self.client.patch(
            f'/api/menu/items/{other_item.pk}/', {'price': '1.00'}
        )
        self.assertIn(resp.status_code, [
            status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND,
        ])


# ── Plan-limit regressions ─────────────────────────────────────────────────────

class MenuItemMaxListingsTest(TestCase):
    """MenuItem creation must respect the tenant's plan max_listings cap."""
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('gatemenu')
        self.owner = make_user('owner@gatemenu.com', self.tenant)
        self.client.defaults['HTTP_HOST'] = 'gatemenu.bizal.al'
        self.client.force_authenticate(user=self.owner)
        self.cat = make_category(self.tenant)

    def test_max_listings_enforced_for_menu_items(self):
        from tenants.models import TenantFeature
        TenantFeature.objects.update_or_create(
            tenant=self.tenant, key='max_listings',
            defaults={'value': '1', 'is_custom_grant': True},
        )
        make_item(self.cat, self.tenant, 'Existing')
        resp = self.client.post('/api/menu/items/', {
            'category': str(self.cat.pk), 'name': 'Overflow',
            'price': '600.00', 'is_available': True,
        })
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(MenuItem.objects.filter(tenant=self.tenant).count(), 1)
