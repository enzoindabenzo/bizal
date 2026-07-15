from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from accounts.models import User
from tenants.models import Tenant
from .models import RoomType, Room, SeasonalPrice


def make_tenant(slug, plan='pro'):
    return Tenant.objects.create(
        name=slug.title(), slug=slug, plan=plan,
        is_active=True, business_type='hotel',
    )


def make_user(email, tenant, role='owner'):
    return User.objects.create_user(
        email=email, password='pass1234', tenant=tenant, role=role,
    )


def make_room_type(tenant, name='Standard', price=5000):
    return RoomType.objects.create(
        tenant=tenant, name=name, base_price=price, capacity=2,
    )


def make_room(tenant, room_type, number='101', floor=1):
    return Room.objects.create(
        tenant=tenant, room_type=room_type,
        room_number=number, floor=floor, status='available',
    )


# ── Public listing ────────────────────────────────────────────────────────────

class RoomTypePublicTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('hotelbiz')
        self.other_tenant = make_tenant('otherhotel')
        self.client.defaults['HTTP_HOST'] = 'hotelbiz.bizal.al'

        self.rt = make_room_type(self.tenant, 'Deluxe', 8000)
        make_room(self.tenant, self.rt, '101')
        make_room(self.tenant, self.rt, '102')
        make_room_type(self.other_tenant, 'Suite', 15000)

    def test_public_can_list_room_types(self):
        resp = self.client.get('/api/hotels/room-types/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        names = [rt['name'] for rt in ((resp.data['results'] if isinstance(resp.data, dict) else resp.data))]
        self.assertIn('Deluxe', names)
        self.assertNotIn('Suite', names)  # other tenant

    def test_public_can_get_room_type_detail(self):
        resp = self.client.get(f'/api/hotels/room-types/{self.rt.pk}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['name'], 'Deluxe')
        self.assertEqual(float(resp.data['base_price']), 8000.0)

    def test_room_list_for_type(self):
        resp = self.client.get(f'/api/hotels/room-types/{self.rt.pk}/rooms/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        numbers = [r['room_number'] for r in ((resp.data['results'] if isinstance(resp.data, dict) else resp.data))]
        self.assertIn('101', numbers)
        self.assertIn('102', numbers)


# ── Owner management ──────────────────────────────────────────────────────────

class RoomTypeOwnerTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('ownhotel')
        self.owner = make_user('owner@ownhotel.com', self.tenant)
        self.customer = make_user('cust@ownhotel.com', self.tenant, 'customer')
        self.client.defaults['HTTP_HOST'] = 'ownhotel.bizal.al'

    def test_owner_can_create_room_type(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.post('/api/hotels/room-types/create/', {
            'name': 'Presidential Suite',
            'base_price': '25000.00',
            'capacity': 4,
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(RoomType.objects.filter(
            tenant=self.tenant, name='Presidential Suite'
        ).exists())

    def test_owner_can_update_room_type(self):
        rt = make_room_type(self.tenant, 'Old Name', 3000)
        self.client.force_authenticate(user=self.owner)
        resp = self.client.patch(
            f'/api/hotels/room-types/{rt.pk}/', {'base_price': '3500.00'}
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        rt.refresh_from_db()
        self.assertEqual(float(rt.base_price), 3500.0)

    def test_owner_can_delete_room_type(self):
        rt = make_room_type(self.tenant, 'To Delete', 1000)
        self.client.force_authenticate(user=self.owner)
        resp = self.client.delete(f'/api/hotels/room-types/{rt.pk}/')
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)

    def test_customer_cannot_manage_room_types(self):
        self.client.force_authenticate(user=self.customer)
        resp = self.client.post('/api/hotels/room-types/create/', {
            'name': 'Hacker Suite', 'base_price': '1.00', 'capacity': 1,
        })
        self.assertIn(resp.status_code, [
            status.HTTP_403_FORBIDDEN, status.HTTP_401_UNAUTHORIZED,
        ])


# ── Seasonal pricing ──────────────────────────────────────────────────────────

class SeasonalPriceTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('seasonhotel')
        self.owner = make_user('owner@seasonhotel.com', self.tenant)
        self.rt = make_room_type(self.tenant, 'Standard', 5000)
        self.client.defaults['HTTP_HOST'] = 'seasonhotel.bizal.al'

    def test_owner_can_add_seasonal_price(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.post(
            f'/api/hotels/room-types/{self.rt.pk}/seasonal-prices/',
            {
                'name': 'Summer 2026',
                'start_date': '2026-07-01',
                'end_date': '2026-08-31',
                'price': '8000.00',
            }
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(SeasonalPrice.objects.filter(
            tenant=self.tenant, name='Summer 2026'
        ).exists())

    def test_seasonal_prices_visible_in_room_type_detail(self):
        SeasonalPrice.objects.create(
            tenant=self.tenant, room_type=self.rt,
            name='Winter', start_date='2026-12-01', end_date='2026-12-31', price=3000,
        )
        self.client.force_authenticate(user=self.owner)
        resp = self.client.get(f'/api/hotels/room-types/{self.rt.pk}/')
        self.assertIn('seasonal_prices', resp.data)
        self.assertEqual(len(resp.data['seasonal_prices']), 1)


# ── Room CRUD ─────────────────────────────────────────────────────────────────

class RoomCRUDTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('roomcrud')
        self.other_tenant = make_tenant('roomother')
        self.owner = make_user('owner@roomcrud.com', self.tenant)
        self.customer = make_user('cust@roomcrud.com', self.tenant, 'customer')
        self.rt = make_room_type(self.tenant, 'Standard', 5000)
        self.room = make_room(self.tenant, self.rt, '101', floor=1)
        self.client.defaults['HTTP_HOST'] = 'roomcrud.bizal.al'

    def test_owner_can_create_room_under_type(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.post(f'/api/hotels/room-types/{self.rt.pk}/rooms/', {
            'room_number': '202', 'floor': 2, 'status': 'available',
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(Room.objects.filter(tenant=self.tenant, room_number='202').exists())

    def test_owner_can_update_room(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.patch(f'/api/hotels/rooms/{self.room.pk}/', {'status': 'maintenance'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.room.refresh_from_db()
        self.assertEqual(self.room.status, 'maintenance')

    def test_owner_can_delete_room(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.delete(f'/api/hotels/rooms/{self.room.pk}/')
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Room.objects.filter(pk=self.room.pk).exists())

    def test_customer_cannot_create_room(self):
        self.client.force_authenticate(user=self.customer)
        resp = self.client.post(f'/api/hotels/room-types/{self.rt.pk}/rooms/', {
            'room_number': '999', 'floor': 1, 'status': 'available',
        })
        self.assertIn(resp.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_401_UNAUTHORIZED])

    def test_cross_tenant_room_create_blocked(self):
        """Owner of tenant A cannot POST rooms under tenant B's room type."""
        other_rt = make_room_type(self.other_tenant, 'Suite', 10000)
        self.client.force_authenticate(user=self.owner)
        resp = self.client.post(f'/api/hotels/room-types/{other_rt.pk}/rooms/', {
            'room_number': '001', 'floor': 1, 'status': 'available',
        })
        # The view's perform_create raises PermissionDenied when the room_type
        # doesn't belong to request.tenant.
        self.assertIn(resp.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

    def test_cross_tenant_room_update_blocked(self):
        """Owner of tenant A cannot PATCH a room belonging to tenant B."""
        other_rt = make_room_type(self.other_tenant, 'Suite', 10000)
        other_room = make_room(self.other_tenant, other_rt, '999')
        self.client.force_authenticate(user=self.owner)
        resp = self.client.patch(f'/api/hotels/rooms/{other_room.pk}/', {'status': 'maintenance'})
        self.assertIn(resp.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

    def test_room_list_scoped_to_tenant(self):
        other_rt = make_room_type(self.other_tenant, 'Suite', 10000)
        make_room(self.other_tenant, other_rt, '999')
        self.client.force_authenticate(user=self.owner)
        resp = self.client.get('/api/hotels/rooms/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        numbers = [r['room_number'] for r in (resp.data.get('results', resp.data))]
        self.assertIn('101', numbers)
        self.assertNotIn('999', numbers)


class FindAvailableRoomTest(TestCase):
    """
    Tests for the find-available-room endpoint, added so the public storefront
    (which only lists RoomType objects, never individual Room numbers) can
    resolve "a Deluxe Room for these dates" to something bookable.
    """
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('findroombiz')
        self.client.defaults['HTTP_HOST'] = 'findroombiz.bizal.al'
        self.rt = make_room_type(self.tenant, 'Deluxe', 7000)
        self.room1 = make_room(self.tenant, self.rt, '101')
        self.room2 = make_room(self.tenant, self.rt, '102')

    def test_finds_an_available_room(self):
        resp = self.client.get('/api/hotels/find-available-room/', {
            'room_type_id': str(self.rt.id),
            'start_date': '2026-10-01',
            'end_date': '2026-10-03',
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn(resp.data['room_id'], [str(self.room1.id), str(self.room2.id)])
        self.assertEqual(resp.data['total_price'], '14000.00')

    def test_skips_room_already_booked_for_dates(self):
        from bookings.models import Booking
        from hotels.models import RoomBooking
        booking = Booking.objects.create(
            tenant=self.tenant, booking_type='room_booking', status='confirmed',
            start_date='2026-10-01', end_date='2026-10-03',
            resource_type='room', resource_id=str(self.room1.id),
            guest_name='Existing Guest', total_price=14000,
        )
        RoomBooking.objects.create(room=self.room1, booking=booking)

        resp = self.client.get('/api/hotels/find-available-room/', {
            'room_type_id': str(self.rt.id),
            'start_date': '2026-10-01',
            'end_date': '2026-10-03',
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['room_id'], str(self.room2.id))

    def test_no_rooms_available_returns_409(self):
        from bookings.models import Booking
        from hotels.models import RoomBooking
        for room in (self.room1, self.room2):
            b = Booking.objects.create(
                tenant=self.tenant, booking_type='room_booking', status='confirmed',
                start_date='2026-10-01', end_date='2026-10-03',
                resource_type='room', resource_id=str(room.id),
                guest_name='Guest', total_price=14000,
            )
            RoomBooking.objects.create(room=room, booking=b)

        resp = self.client.get('/api/hotels/find-available-room/', {
            'room_type_id': str(self.rt.id),
            'start_date': '2026-10-01',
            'end_date': '2026-10-03',
        })
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)

    def test_missing_params_rejected(self):
        resp = self.client.get('/api/hotels/find-available-room/', {
            'room_type_id': str(self.rt.id),
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_room_type_404(self):
        resp = self.client.get('/api/hotels/find-available-room/', {
            'room_type_id': '00000000-0000-0000-0000-000000000000',
            'start_date': '2026-10-01',
            'end_date': '2026-10-03',
        })
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


# ── Plan-limit / feature-gating regressions ────────────────────────────────────

class HotelsFeatureGatingTest(TestCase):
    """
    Regression tests: RoomType/Room management endpoints must be gated on
    HasTenantFeature('bookings'), and creation must respect the tenant's
    plan max_listings cap. Neither check existed previously — an owner on
    any plan could create unlimited RoomTypes/Rooms, and a tenant whose
    plan had 'bookings' disabled could still manage hotel inventory (even
    though guests couldn't actually book any of it).
    """
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('gatehotel')
        self.owner = make_user('owner@gatehotel.com', self.tenant)
        self.client.defaults['HTTP_HOST'] = 'gatehotel.bizal.al'
        self.client.force_authenticate(user=self.owner)

    def test_create_blocked_when_plan_lacks_bookings_feature(self):
        from tenants.models import TenantFeature
        TenantFeature.objects.update_or_create(
            tenant=self.tenant, key='bookings',
            defaults={'value': 'False', 'is_custom_grant': True},
        )
        resp = self.client.post('/api/hotels/room-types/create/', {
            'name': 'Should Not Be Created', 'base_price': '1000.00', 'capacity': 2,
        })
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(RoomType.objects.filter(tenant=self.tenant, name='Should Not Be Created').exists())

    def test_room_create_blocked_when_plan_lacks_bookings_feature(self):
        from tenants.models import TenantFeature
        rt = make_room_type(self.tenant, 'Standard', 5000)
        TenantFeature.objects.update_or_create(
            tenant=self.tenant, key='bookings',
            defaults={'value': 'False', 'is_custom_grant': True},
        )
        resp = self.client.post(f'/api/hotels/room-types/{rt.pk}/rooms/', {
            'room_number': '999', 'floor': 1, 'status': 'available',
        })
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_max_listings_enforced_for_room_types(self):
        from tenants.models import TenantFeature
        TenantFeature.objects.update_or_create(
            tenant=self.tenant, key='max_listings',
            defaults={'value': '2', 'is_custom_grant': True},
        )
        make_room_type(self.tenant, 'One', 1000)
        make_room_type(self.tenant, 'Two', 1000)
        resp = self.client.post('/api/hotels/room-types/create/', {
            'name': 'Three', 'base_price': '1000.00', 'capacity': 2,
        })
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(RoomType.objects.filter(tenant=self.tenant).count(), 2)

    def test_max_listings_allows_creation_under_cap(self):
        from tenants.models import TenantFeature
        TenantFeature.objects.update_or_create(
            tenant=self.tenant, key='max_listings',
            defaults={'value': '2', 'is_custom_grant': True},
        )
        make_room_type(self.tenant, 'One', 1000)
        resp = self.client.post('/api/hotels/room-types/create/', {
            'name': 'Two', 'base_price': '1000.00', 'capacity': 2,
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_room_booking_create_blocked_when_plan_lacks_bookings_feature(self):
        from tenants.models import TenantFeature
        rt = make_room_type(self.tenant, 'Standard', 5000)
        room = make_room(self.tenant, rt, '201')
        TenantFeature.objects.update_or_create(
            tenant=self.tenant, key='bookings',
            defaults={'value': 'False', 'is_custom_grant': True},
        )
        anon = APIClient()
        anon.defaults['HTTP_HOST'] = 'gatehotel.bizal.al'
        resp = anon.post('/api/hotels/bookings/', {
            'room_id': str(room.id),
            'start_date': '2026-11-01', 'end_date': '2026-11-03',
            'guest_name': 'Guest', 'guest_email': 'guest@example.com',
        })
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
