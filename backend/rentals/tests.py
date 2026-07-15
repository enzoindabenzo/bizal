from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from accounts.models import User
from tenants.models import Tenant
from .models import RentalItem


def make_tenant(slug, plan='pro'):
    return Tenant.objects.create(
        name=slug.title(), slug=slug, plan=plan,
        is_active=True, business_type='car_rental',
    )


def make_user(email, tenant, role='owner'):
    return User.objects.create_user(
        email=email, password='pass1234', tenant=tenant, role=role,
    )


def make_item(tenant, name='BMW 530i', rental_type='car', price=5000, city='Tiranë'):
    return RentalItem.objects.create(
        tenant=tenant, name=name, rental_type=rental_type,
        price_per_day=price, city=city, status='available',
    )


# ── Public listing ────────────────────────────────────────────────────────────

class RentalPublicTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('rentalbiz')
        self.other_tenant = make_tenant('otherrental')
        self.client.defaults['HTTP_HOST'] = 'rentalbiz.bizal.al'

        self.car = make_item(self.tenant, 'Benz E200', 'car', 6000, 'Tiranë')
        self.boat = make_item(self.tenant, 'Sea Ray', 'boat', 15000, 'Sarandë')
        make_item(self.other_tenant, 'Hidden Car', 'car', 4000, 'Durrës')

    def test_public_can_list_rentals(self):
        resp = self.client.get('/api/rentals/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        names = [r['name'] for r in ((resp.data['results'] if isinstance(resp.data, dict) else resp.data))]
        self.assertIn('Benz E200', names)
        self.assertIn('Sea Ray', names)
        self.assertNotIn('Hidden Car', names)

    def test_filter_by_type(self):
        resp = self.client.get('/api/rentals/?rental_type=boat')
        names = [r['name'] for r in ((resp.data['results'] if isinstance(resp.data, dict) else resp.data))]
        self.assertIn('Sea Ray', names)
        self.assertNotIn('Benz E200', names)

    def test_filter_by_city(self):
        resp = self.client.get('/api/rentals/?city=Sarandë')
        names = [r['name'] for r in ((resp.data['results'] if isinstance(resp.data, dict) else resp.data))]
        self.assertIn('Sea Ray', names)
        self.assertNotIn('Benz E200', names)

    def test_filter_by_status(self):
        self.car.status = 'rented'
        self.car.save()
        resp = self.client.get('/api/rentals/?status=available')
        names = [r['name'] for r in ((resp.data['results'] if isinstance(resp.data, dict) else resp.data))]
        self.assertNotIn('Benz E200', names)
        self.assertIn('Sea Ray', names)

    def test_public_can_get_detail(self):
        resp = self.client.get(f'/api/rentals/{self.car.pk}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['name'], 'Benz E200')

    def test_featured_endpoint(self):
        self.boat.is_featured = True
        self.boat.save()
        resp = self.client.get('/api/rentals/featured/')
        names = [r['name'] for r in ((resp.data['results'] if isinstance(resp.data, dict) else resp.data))]
        self.assertIn('Sea Ray', names)
        self.assertNotIn('Benz E200', names)


# ── Owner management ──────────────────────────────────────────────────────────

class RentalOwnerTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('managerental')
        self.owner = make_user('owner@managerental.com', self.tenant)
        self.customer = make_user('cust@managerental.com', self.tenant, 'customer')
        self.client.defaults['HTTP_HOST'] = 'managerental.bizal.al'

    def test_owner_can_create_item(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.post('/api/rentals/create/', {
            'name': 'Porsche Cayenne',
            'rental_type': 'car',
            'price_per_day': '9000.00',
            'city': 'Tiranë',
            'deposit': '50000.00',
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_owner_can_update_status(self):
        item = make_item(self.tenant)
        self.client.force_authenticate(user=self.owner)
        resp = self.client.patch(
            f'/api/rentals/{item.pk}/manage/', {'status': 'maintenance'}
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        item.refresh_from_db()
        self.assertEqual(item.status, 'maintenance')

    def test_owner_can_delete_item(self):
        item = make_item(self.tenant, 'Delete Me')
        self.client.force_authenticate(user=self.owner)
        resp = self.client.delete(f'/api/rentals/{item.pk}/manage/')
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(RentalItem.objects.filter(pk=item.pk).exists())

    def test_customer_cannot_manage(self):
        self.client.force_authenticate(user=self.customer)
        resp = self.client.post('/api/rentals/create/', {
            'name': 'Nope', 'rental_type': 'car',
            'price_per_day': '1.00', 'city': 'X',
        })
        self.assertIn(resp.status_code, [
            status.HTTP_403_FORBIDDEN, status.HTTP_401_UNAUTHORIZED,
        ])


# ── Availability check ────────────────────────────────────────────────────────

class RentalAvailabilityTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('availrental')
        self.item = make_item(self.tenant, 'Mercedes CLA')
        self.client.defaults['HTTP_HOST'] = 'availrental.bizal.al'

    def test_available_item_returns_true(self):
        resp = self.client.get(
            f'/api/rentals/{self.item.pk}/availability/',
            {'start_date': '2026-10-01', 'end_date': '2026-10-05'},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data.get('available'))

    def test_missing_dates_returns_400(self):
        resp = self.client.get(f'/api/rentals/{self.item.pk}/availability/')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


# ── Consolidated endpoints ──────────────────────────────────────────────────
# The tenant admin UI calls POST /rentals/ and PATCH/DELETE /rentals/<id>/
# directly (matching every other resource's URL convention), not the
# legacy /create/ and /<pk>/manage/ paths. Previously these routes only
# supported GET, so the UI's add/edit/delete-item flows were silently
# hitting 405. Mirrors the same fix applied to inventory.

class RentalConsolidatedEndpointTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('consolidatedrental')
        self.owner = make_user('owner@consolidatedrental.com', self.tenant)
        self.customer = make_user('cust@consolidatedrental.com', self.tenant, 'customer')
        self.client.defaults['HTTP_HOST'] = 'consolidatedrental.bizal.al'

    def test_owner_can_create_item_via_list_endpoint(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.post('/api/rentals/', {
            'name': 'Audi Q7',
            'rental_type': 'car',
            'price_per_day': '8000.00',
            'city': 'Tiranë',
            'deposit': '40000.00',
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(RentalItem.objects.filter(tenant=self.tenant, name='Audi Q7').exists())

    def test_anonymous_cannot_create_item_via_list_endpoint(self):
        resp = self.client.post('/api/rentals/', {
            'name': 'Hack', 'rental_type': 'car', 'price_per_day': '1.00', 'city': 'X',
        })
        self.assertIn(resp.status_code, [
            status.HTTP_403_FORBIDDEN, status.HTTP_401_UNAUTHORIZED,
        ])

    def test_owner_can_update_item_via_detail_endpoint(self):
        item = make_item(self.tenant, 'VW Golf')
        self.client.force_authenticate(user=self.owner)
        resp = self.client.patch(f'/api/rentals/{item.pk}/', {'status': 'maintenance'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        item.refresh_from_db()
        self.assertEqual(item.status, 'maintenance')

    def test_owner_can_delete_item_via_detail_endpoint(self):
        item = make_item(self.tenant, 'Old Scooter')
        self.client.force_authenticate(user=self.owner)
        resp = self.client.delete(f'/api/rentals/{item.pk}/')
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(RentalItem.objects.filter(pk=item.pk).exists())

    def test_customer_cannot_update_item_via_detail_endpoint(self):
        item = make_item(self.tenant, 'Locked Item')
        self.client.force_authenticate(user=self.customer)
        resp = self.client.patch(f'/api/rentals/{item.pk}/', {'status': 'maintenance'})
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_public_get_on_detail_endpoint_excludes_unavailable(self):
        item = make_item(self.tenant, 'In Maintenance')
        item.status = 'maintenance'
        item.save(update_fields=['status'])
        resp = self.client.get(f'/api/rentals/{item.pk}/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_owner_can_reach_unavailable_item_via_detail_endpoint(self):
        item = make_item(self.tenant, 'Currently Rented')
        item.status = 'rented'
        item.save(update_fields=['status'])
        self.client.force_authenticate(user=self.owner)
        resp = self.client.patch(f'/api/rentals/{item.pk}/', {'status': 'available'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        item.refresh_from_db()
        self.assertEqual(item.status, 'available')

    def test_legacy_create_and_manage_aliases_still_work(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.post('/api/rentals/create/', {
            'name': 'Legacy Path Item',
            'rental_type': 'car',
            'price_per_day': '2000.00',
            'city': 'Tiranë',
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        item = RentalItem.objects.get(name='Legacy Path Item')
        resp = self.client.patch(f'/api/rentals/{item.pk}/manage/', {'status': 'maintenance'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        item.refresh_from_db()
        self.assertEqual(item.status, 'maintenance')


# ── Plan-limit / feature-gating regressions ────────────────────────────────────

class RentalsFeatureGatingTest(TestCase):
    """
    Regression tests: RentalItem management endpoints must be gated on
    HasTenantFeature('bookings'), and creation must respect the tenant's
    plan max_listings cap.
    """
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('gaterental')
        self.owner = make_user('owner@gaterental.com', self.tenant)
        self.client.defaults['HTTP_HOST'] = 'gaterental.bizal.al'
        self.client.force_authenticate(user=self.owner)

    def test_create_blocked_when_plan_lacks_bookings_feature(self):
        from tenants.models import TenantFeature
        TenantFeature.objects.update_or_create(
            tenant=self.tenant, key='bookings',
            defaults={'value': 'False', 'is_custom_grant': True},
        )
        resp = self.client.post('/api/rentals/', {
            'name': 'Blocked Car', 'rental_type': 'car',
            'price_per_day': '5000.00', 'city': 'Tiranë',
        })
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(RentalItem.objects.filter(tenant=self.tenant, name='Blocked Car').exists())

    def test_max_listings_enforced_for_rental_items(self):
        from tenants.models import TenantFeature
        TenantFeature.objects.update_or_create(
            tenant=self.tenant, key='max_listings',
            defaults={'value': '1', 'is_custom_grant': True},
        )
        make_item(self.tenant, 'Existing Car')
        resp = self.client.post('/api/rentals/', {
            'name': 'Overflow Car', 'rental_type': 'car',
            'price_per_day': '5000.00', 'city': 'Tiranë',
        })
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(RentalItem.objects.filter(tenant=self.tenant).count(), 1)
