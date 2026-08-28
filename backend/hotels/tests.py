from django.test import TestCase

from rest_framework.test import APIClient

from rest_framework import status

from accounts.models import User

from tenants.models import Tenant

from .models import RoomType, Room, SeasonalPrice

from unittest.mock import patch

from .models import RoomType, Room, RoomBooking

import datetime

from bookings.models import Booking

from hotels.models import RoomType, Room, SeasonalPrice, RoomBooking, is_room_available


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


def make_tenant__gaps(slug, plan='pro'):
    return Tenant.objects.create(
        name=slug.title(), slug=slug, plan=plan,
        is_active=True, business_type='hotel',
    )


def make_user__gaps(email, tenant, role='owner'):
    return User.objects.create_user(email=email, password='pass1234', tenant=tenant, role=role)


def make_room_type__gaps(tenant, name='Standard', price=5000):
    return RoomType.objects.create(tenant=tenant, name=name, base_price=price, capacity=2)


def make_room__gaps(tenant, room_type, number='101', floor=1, status='available'):
    return Room.objects.create(tenant=tenant, room_type=room_type, room_number=number, floor=floor, status=status)


class RoomDetailPublicGetTest(TestCase):
    """RoomDetailView.get_permissions: GET is AllowAny (line 85)."""

    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant__gaps('roomdetailpub')
        self.rt = make_room_type__gaps(self.tenant, 'Standard', 5000)
        self.room = make_room__gaps(self.tenant, self.rt, '101')
        self.client.defaults['HTTP_HOST'] = 'roomdetailpub.bizal.al'

    def test_anonymous_can_get_single_room(self):
        resp = self.client.get(f'/api/hotels/rooms/{self.room.pk}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['room_number'], '101')


class SeasonalPriceListAndIdorTest(TestCase):
    """
    SeasonalPriceView.get_queryset (line 97) and the cross-tenant
    RoomType.DoesNotExist branch in perform_create (lines 109-110).
    """

    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant__gaps('seasongap')
        self.other_tenant = make_tenant__gaps('seasongapother')
        self.owner = make_user__gaps('owner@seasongap.com', self.tenant)
        self.rt = make_room_type__gaps(self.tenant, 'Standard', 5000)
        self.other_rt = make_room_type__gaps(self.other_tenant, 'Suite', 9000)
        self.client.defaults['HTTP_HOST'] = 'seasongap.bizal.al'

    def test_owner_can_list_seasonal_prices(self):
        from .models import SeasonalPrice
        SeasonalPrice.objects.create(
            tenant=self.tenant, room_type=self.rt,
            name='Spring', start_date='2026-04-01', end_date='2026-04-30', price=6000,
        )
        self.client.force_authenticate(user=self.owner)
        resp = self.client.get(f'/api/hotels/room-types/{self.rt.pk}/seasonal-prices/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        names = [p['name'] for p in (resp.data.get('results', resp.data))]
        self.assertIn('Spring', names)

    def test_cross_tenant_seasonal_price_create_blocked(self):
        """
        Owner of `tenant` POSTs to the seasonal-prices endpoint under a
        room_type pk that belongs to `other_tenant` -> PermissionDenied,
        not a leaked cross-tenant SeasonalPrice.
        """
        self.client.force_authenticate(user=self.owner)
        resp = self.client.post(
            f'/api/hotels/room-types/{self.other_rt.pk}/seasonal-prices/',
            {
                'name': 'Hijacked', 'start_date': '2026-05-01',
                'end_date': '2026-05-10', 'price': '1.00',
            },
        )
        self.assertIn(resp.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])
        from .models import SeasonalPrice
        self.assertFalse(SeasonalPrice.objects.filter(name='Hijacked').exists())


class RoomBookingOptionsMetadataTest(TestCase):
    """
    RoomBookingListCreateView.get_serializer_class's POST branch (line 169)
    is only reached via DRF's metadata/OPTIONS handling, since the view's
    own create() builds RoomBookingCreateSerializer directly without going
    through get_serializer_class.
    """

    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant__gaps('hoptions')
        self.owner = make_user__gaps('owner@hoptions.com', self.tenant)
        self.client.defaults['HTTP_HOST'] = 'hoptions.bizal.al'

    def test_options_request_describes_both_methods(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.options('/api/hotels/bookings/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('actions', resp.data)


class RoomsCalendarNullDatesAndToWindowTest(TestCase):
    """
    rooms_calendar: the `sd is None or ed is None` guard (line 447, reachable
    since Booking.start_date/end_date are nullable) and the `to`-window
    exclusion branch (line 451; the pre-existing test only covered `from`).
    """

    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant__gaps('hcalgap')
        self.owner = make_user__gaps('owner@hcalgap.com', self.tenant)
        self.rt = make_room_type__gaps(self.tenant, 'Deluxe', 9000)
        self.room1 = make_room__gaps(self.tenant, self.rt, '101')
        self.client.defaults['HTTP_HOST'] = 'hcalgap.bizal.al'

    def _create_booking(self, room, start, end, guest='Gu'):
        from bookings.models import Booking
        booking = Booking.objects.create(
            tenant=self.tenant, booking_type='room_booking', status='confirmed',
            start_date=start, end_date=end, guest_name=guest, guest_email='gu@example.com',
            resource_type='room', resource_id=str(room.pk),
        )
        return RoomBooking.objects.create(room=room, booking=booking)

    def test_bookings_with_null_dates_are_skipped(self):
        self._create_booking(self.room1, None, None)
        self.client.force_authenticate(user=self.owner)
        resp = self.client.get('/api/hotels/rooms/calendar/')
        self.assertEqual(resp.status_code, 200)
        room1_data = next(r for r in resp.data['rooms'] if r['room_id'] == str(self.room1.pk))
        self.assertEqual(room1_data['booked_ranges'], [])

    @patch('notifications.tasks.send_booking_confirmation_email.delay')
    def test_to_window_excludes_bookings_starting_after_window(self, mock_delay):
        self.client.post('/api/hotels/bookings/', {
            'room_id': str(self.room1.pk), 'start_date': '2027-04-01', 'end_date': '2027-04-03',
            'guest_name': 'Gu', 'guest_email': 'gu@example.com',
        })
        self.client.force_authenticate(user=self.owner)
        # Window closes before the booking even starts -> excluded by the
        # `sd >= window_end` branch.
        resp = self.client.get('/api/hotels/rooms/calendar/?to=2027-03-01')
        self.assertEqual(resp.status_code, 200)
        room1_data = next(r for r in resp.data['rooms'] if r['room_id'] == str(self.room1.pk))
        self.assertEqual(room1_data['booked_ranges'], [])


def make_tenant__models_gaps(slug='hotels-models-gap'):
    return Tenant.objects.create(
        name='Hotels Models Co', slug=slug, business_type='hotel', plan='pro', is_active=True,
    )


class HotelsModelsStrGapsTests(TestCase):
    def setUp(self):
        self.tenant = make_tenant__models_gaps()
        self.room_type = RoomType.objects.create(
            tenant=self.tenant, name='Deluxe', base_price=10000, capacity=2,
        )
        self.room = Room.objects.create(
            tenant=self.tenant, room_type=self.room_type, room_number='201', floor=2, status='available',
        )

    def test_room_type_str(self):
        self.assertEqual(str(self.room_type), 'Deluxe')

    def test_room_str(self):
        self.assertEqual(str(self.room), 'Room 201 (Deluxe)')

    def test_seasonal_price_str(self):
        sp = SeasonalPrice.objects.create(
            tenant=self.tenant, room_type=self.room_type, name='Summer',
            start_date=datetime.date(2026, 6, 1), end_date=datetime.date(2026, 8, 31), price=15000,
        )
        self.assertEqual(str(sp), 'Summer: 2026-06-01 - 2026-08-31')

    def test_room_booking_str(self):
        booking = Booking.objects.create(
            tenant=self.tenant, booking_type='room_booking', status='confirmed',
            start_date=datetime.date(2026, 9, 1), end_date=datetime.date(2026, 9, 4),
        )
        rb = RoomBooking.objects.create(room=self.room, booking=booking)
        self.assertEqual(str(rb), f'Room 201 → Booking {booking.pk}')


class IsRoomAvailableGapsTests(TestCase):
    def setUp(self):
        self.tenant = make_tenant__models_gaps('hotels-avail-gap')
        self.room_type = RoomType.objects.create(
            tenant=self.tenant, name='Standard', base_price=5000, capacity=2,
        )

    def test_room_not_available_status_short_circuits(self):
        room = Room.objects.create(
            tenant=self.tenant, room_type=self.room_type, room_number='301', floor=3, status='maintenance',
        )
        self.assertFalse(
            is_room_available(room, datetime.date(2026, 10, 1), datetime.date(2026, 10, 4))
        )

    def test_exclude_booking_id_excludes_own_booking_from_overlap_check(self):
        room = Room.objects.create(
            tenant=self.tenant, room_type=self.room_type, room_number='302', floor=3, status='available',
        )
        booking = Booking.objects.create(
            tenant=self.tenant, booking_type='room_booking', status='confirmed',
            start_date=datetime.date(2026, 10, 1), end_date=datetime.date(2026, 10, 4),
        )
        RoomBooking.objects.create(room=room, booking=booking)
        # Same dates would normally overlap with itself, but excluding its
        # own booking id should report the room as available.
        self.assertTrue(
            is_room_available(
                room, datetime.date(2026, 10, 1), datetime.date(2026, 10, 4),
                exclude_booking_id=booking.pk,
            )
        )
        # Without the exclusion, the same overlap is correctly rejected.
        self.assertFalse(
            is_room_available(room, datetime.date(2026, 10, 1), datetime.date(2026, 10, 4))
        )


def make_tenant__room_bookings(slug, plan='pro', feature_bookings=True):
    t = Tenant.objects.create(
        name=slug.title(), slug=slug, plan=plan,
        is_active=True, business_type='hotel',
    )
    return t


def make_user__room_bookings(email, tenant, role='owner'):
    return User.objects.create_user(email=email, password='pass1234', tenant=tenant, role=role)


def make_room_type__room_bookings(tenant, name='Standard', price=5000):
    return RoomType.objects.create(tenant=tenant, name=name, base_price=price, capacity=2)


def make_room__room_bookings(tenant, room_type, number='101', floor=1, status='available'):
    return Room.objects.create(tenant=tenant, room_type=room_type, room_number=number, floor=floor, status=status)


class RoomBookingCreateTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant__room_bookings('hbook')
        self.owner = make_user__room_bookings('owner@hbook.com', self.tenant)
        self.rt = make_room_type__room_bookings(self.tenant, 'Deluxe', 10000)
        self.room = make_room__room_bookings(self.tenant, self.rt, '201')
        self.client.defaults['HTTP_HOST'] = 'hbook.bizal.al'

    @patch('notifications.tasks.send_booking_confirmation_email.delay')
    def test_create_room_booking_success(self, mock_delay):
        resp = self.client.post('/api/hotels/bookings/', {
            'room_id': str(self.room.pk), 'start_date': '2026-09-01', 'end_date': '2026-09-04',
            'guest_name': 'Ana', 'guest_email': 'ana@example.com',
        })
        self.assertEqual(resp.status_code, 201)
        mock_delay.assert_called_once()
        self.assertEqual(RoomBooking.objects.count(), 1)

    def test_create_room_booking_end_before_start_rejected(self):
        resp = self.client.post('/api/hotels/bookings/', {
            'room_id': str(self.room.pk), 'start_date': '2026-09-04', 'end_date': '2026-09-01',
            'guest_name': 'Ana', 'guest_email': 'ana@example.com',
        })
        self.assertEqual(resp.status_code, 400)

    def test_create_room_booking_room_not_found(self):
        import uuid
        resp = self.client.post('/api/hotels/bookings/', {
            'room_id': str(uuid.uuid4()), 'start_date': '2026-09-01', 'end_date': '2026-09-04',
            'guest_name': 'Ana', 'guest_email': 'ana@example.com',
        })
        self.assertEqual(resp.status_code, 404)

    @patch('notifications.tasks.send_booking_confirmation_email.delay')
    def test_create_room_booking_overlap_conflict(self, mock_delay):
        self.client.post('/api/hotels/bookings/', {
            'room_id': str(self.room.pk), 'start_date': '2026-09-01', 'end_date': '2026-09-04',
            'guest_name': 'Ana', 'guest_email': 'ana@example.com',
        })
        resp2 = self.client.post('/api/hotels/bookings/', {
            'room_id': str(self.room.pk), 'start_date': '2026-09-02', 'end_date': '2026-09-06',
            'guest_name': 'Bob', 'guest_email': 'bob@example.com',
        })
        self.assertEqual(resp2.status_code, 409)

    def test_create_room_booking_requires_tenant_subdomain(self):
        self.client.defaults['HTTP_HOST'] = 'bizal.al'
        resp = self.client.post('/api/hotels/bookings/', {
            'room_id': str(self.room.pk), 'start_date': '2026-09-01', 'end_date': '2026-09-04',
            'guest_name': 'Ana', 'guest_email': 'ana@example.com',
        })
        self.assertEqual(resp.status_code, 400)

    def test_create_room_booking_requires_bookings_feature(self):
        with patch('tenants.models.Tenant.has_feature', return_value=False):
            resp = self.client.post('/api/hotels/bookings/', {
                'room_id': str(self.room.pk), 'start_date': '2026-09-01', 'end_date': '2026-09-04',
                'guest_name': 'Ana', 'guest_email': 'ana@example.com',
            })
        self.assertEqual(resp.status_code, 403)

    def test_list_room_bookings_requires_owner(self):
        resp = self.client.get('/api/hotels/bookings/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch('notifications.tasks.send_booking_confirmation_email.delay')
    def test_list_room_bookings_as_owner(self, mock_delay):
        self.client.post('/api/hotels/bookings/', {
            'room_id': str(self.room.pk), 'start_date': '2026-09-01', 'end_date': '2026-09-04',
            'guest_name': 'Ana', 'guest_email': 'ana@example.com',
        })
        self.client.force_authenticate(user=self.owner)
        resp = self.client.get('/api/hotels/bookings/')
        self.assertEqual(resp.status_code, 200)
        data = resp.data['results'] if isinstance(resp.data, dict) else resp.data
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['guest_name'], 'Ana')

    @patch('notifications.tasks.send_booking_confirmation_email.delay')
    def test_list_room_bookings_ordering_is_deterministic(self, mock_delay):
        """
        Regression test: RoomBookingListCreateView paginates RoomBooking
        without an explicit order, and RoomBooking.Meta previously had no
        default ordering either. Postgres doesn't guarantee a stable row
        order for an unordered query, so two identical GETs (or two pages
        of the same list) could return rows in different order — silently
        surfacing as duplicate/missing rows for the owner. Asserts the
        result order is stable across repeated requests.
        """
        rooms = [make_room__room_bookings(self.tenant, self.rt, str(300 + i)) for i in range(5)]
        for i, room in enumerate(rooms):
            self.client.post('/api/hotels/bookings/', {
                'room_id': str(room.pk), 'start_date': '2026-09-01', 'end_date': '2026-09-04',
                'guest_name': f'Guest{i}', 'guest_email': f'guest{i}@example.com',
            })
        self.assertEqual(RoomBooking.objects.count(), 5)

        self.client.force_authenticate(user=self.owner)
        resp1 = self.client.get('/api/hotels/bookings/')
        resp2 = self.client.get('/api/hotels/bookings/')
        data1 = resp1.data['results'] if isinstance(resp1.data, dict) else resp1.data
        data2 = resp2.data['results'] if isinstance(resp2.data, dict) else resp2.data

        ids1 = [row['id'] for row in data1]
        ids2 = [row['id'] for row in data2]
        self.assertEqual(len(ids1), 5)
        self.assertEqual(ids1, ids2)  # same order every time, no dup/missing rows


class RoomBookingDetailTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant__room_bookings('hdetail')
        self.owner = make_user__room_bookings('owner@hdetail.com', self.tenant)
        self.rt = make_room_type__room_bookings(self.tenant, 'Suite', 12000)
        self.room = make_room__room_bookings(self.tenant, self.rt, '301')
        self.client.defaults['HTTP_HOST'] = 'hdetail.bizal.al'

    def _create_booking(self):
        with patch('notifications.tasks.send_booking_confirmation_email.delay'):
            resp = self.client.post('/api/hotels/bookings/', {
                'room_id': str(self.room.pk), 'start_date': '2026-10-01', 'end_date': '2026-10-05',
                'guest_name': 'Chris', 'guest_email': 'chris@example.com',
            })
        return RoomBooking.objects.get()

    def test_detail_view_requires_owner(self):
        rb = self._create_booking()
        resp = self.client.get(f'/api/hotels/bookings/{rb.pk}/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_detail_view_as_owner(self):
        rb = self._create_booking()
        self.client.force_authenticate(user=self.owner)
        resp = self.client.get(f'/api/hotels/bookings/{rb.pk}/')
        self.assertEqual(resp.status_code, 200)

    def test_cancel_room_booking_marks_booking_cancelled(self):
        rb = self._create_booking()
        booking = rb.booking
        self.client.force_authenticate(user=self.owner)
        resp = self.client.delete(f'/api/hotels/bookings/{rb.pk}/')
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'cancelled')
        self.assertFalse(RoomBooking.objects.filter(pk=rb.pk).exists())


class FindAvailableRoomTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant__room_bookings('hfind')
        self.rt = make_room_type__room_bookings(self.tenant, 'Standard', 6000)
        self.room1 = make_room__room_bookings(self.tenant, self.rt, '101')
        self.client.defaults['HTTP_HOST'] = 'hfind.bizal.al'

    def test_find_available_room_missing_params(self):
        resp = self.client.get('/api/hotels/find-available-room/')
        self.assertEqual(resp.status_code, 400)

    def test_find_available_room_success(self):
        resp = self.client.get(
            f'/api/hotels/find-available-room/?room_type_id={self.rt.pk}&start_date=2026-11-01&end_date=2026-11-03'
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['room_id'], str(self.room1.pk))
        self.assertEqual(resp.data['nights'], 2)

    def test_find_available_room_type_not_found(self):
        import uuid
        resp = self.client.get(
            f'/api/hotels/find-available-room/?room_type_id={uuid.uuid4()}&start_date=2026-11-01&end_date=2026-11-03'
        )
        self.assertEqual(resp.status_code, 404)

    def test_find_available_room_invalid_dates(self):
        resp = self.client.get(
            f'/api/hotels/find-available-room/?room_type_id={self.rt.pk}&start_date=not-a-date&end_date=2026-11-03'
        )
        self.assertEqual(resp.status_code, 400)

    def test_find_available_room_end_before_start(self):
        resp = self.client.get(
            f'/api/hotels/find-available-room/?room_type_id={self.rt.pk}&start_date=2026-11-05&end_date=2026-11-01'
        )
        self.assertEqual(resp.status_code, 400)

    @patch('notifications.tasks.send_booking_confirmation_email.delay')
    def test_find_available_room_none_free(self, mock_delay):
        self.client.post('/api/hotels/bookings/', {
            'room_id': str(self.room1.pk), 'start_date': '2026-11-01', 'end_date': '2026-11-03',
            'guest_name': 'X', 'guest_email': 'x@example.com',
        })
        resp = self.client.get(
            f'/api/hotels/find-available-room/?room_type_id={self.rt.pk}&start_date=2026-11-01&end_date=2026-11-03'
        )
        self.assertEqual(resp.status_code, 409)


class RoomTypeBookedRangesTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant__room_bookings('hranges')
        self.rt = make_room_type__room_bookings(self.tenant, 'Deluxe', 8000)
        self.room1 = make_room__room_bookings(self.tenant, self.rt, '101')
        self.room2 = make_room__room_bookings(self.tenant, self.rt, '102')
        self.client.defaults['HTTP_HOST'] = 'hranges.bizal.al'

    def test_not_found(self):
        import uuid
        resp = self.client.get(f'/api/hotels/room-types/{uuid.uuid4()}/booked-ranges/')
        self.assertEqual(resp.status_code, 404)

    def test_no_available_rooms_returns_empty(self):
        self.room1.status = 'maintenance'
        self.room1.save()
        self.room2.status = 'maintenance'
        self.room2.save()
        resp = self.client.get(f'/api/hotels/room-types/{self.rt.pk}/booked-ranges/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['total_rooms'], 0)
        self.assertEqual(resp.data['ranges'], [])

    def test_no_bookings_returns_empty_ranges(self):
        resp = self.client.get(f'/api/hotels/room-types/{self.rt.pk}/booked-ranges/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['total_rooms'], 2)
        self.assertEqual(resp.data['ranges'], [])

    @patch('notifications.tasks.send_booking_confirmation_email.delay')
    def test_partial_occupancy_not_fully_booked(self, mock_delay):
        # Only one of two rooms booked -> not "fully booked"
        self.client.post('/api/hotels/bookings/', {
            'room_id': str(self.room1.pk), 'start_date': '2026-12-01', 'end_date': '2026-12-05',
            'guest_name': 'A', 'guest_email': 'a@example.com',
        })
        resp = self.client.get(f'/api/hotels/room-types/{self.rt.pk}/booked-ranges/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['ranges'], [])

    @patch('notifications.tasks.send_booking_confirmation_email.delay')
    def test_full_occupancy_reported_as_range(self, mock_delay):
        self.client.post('/api/hotels/bookings/', {
            'room_id': str(self.room1.pk), 'start_date': '2026-12-01', 'end_date': '2026-12-05',
            'guest_name': 'A', 'guest_email': 'a@example.com',
        })
        self.client.post('/api/hotels/bookings/', {
            'room_id': str(self.room2.pk), 'start_date': '2026-12-01', 'end_date': '2026-12-05',
            'guest_name': 'B', 'guest_email': 'b@example.com',
        })
        resp = self.client.get(f'/api/hotels/room-types/{self.rt.pk}/booked-ranges/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data['ranges']), 1)
        self.assertEqual(str(resp.data['ranges'][0]['start_date']), '2026-12-01')
        self.assertEqual(str(resp.data['ranges'][0]['end_date']), '2026-12-05')

    @patch('notifications.tasks.send_booking_confirmation_email.delay')
    def test_cancelled_bookings_excluded_from_ranges(self, mock_delay):
        self.client.post('/api/hotels/bookings/', {
            'room_id': str(self.room1.pk), 'start_date': '2026-12-10', 'end_date': '2026-12-12',
            'guest_name': 'A', 'guest_email': 'a@example.com',
        })
        rb = RoomBooking.objects.get()
        rb.booking.status = 'cancelled'
        rb.booking.save(update_fields=['status'])
        resp = self.client.get(f'/api/hotels/room-types/{self.rt.pk}/booked-ranges/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['ranges'], [])


class RoomsCalendarTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant__room_bookings('hcal')
        self.owner = make_user__room_bookings('owner@hcal.com', self.tenant)
        self.rt = make_room_type__room_bookings(self.tenant, 'Deluxe', 9000)
        self.room1 = make_room__room_bookings(self.tenant, self.rt, '101')
        self.room2 = make_room__room_bookings(self.tenant, self.rt, '102')
        self.client.defaults['HTTP_HOST'] = 'hcal.bizal.al'

    def test_requires_owner(self):
        resp = self.client.get('/api/hotels/rooms/calendar/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_returns_all_rooms(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.get('/api/hotels/rooms/calendar/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data['rooms']), 2)

    def test_filters_by_room_type_id(self):
        rt2 = make_room_type__room_bookings(self.tenant, 'Suite', 15000)
        make_room__room_bookings(self.tenant, rt2, '201')
        self.client.force_authenticate(user=self.owner)
        resp = self.client.get(f'/api/hotels/rooms/calendar/?room_type_id={self.rt.pk}')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data['rooms']), 2)

    @patch('notifications.tasks.send_booking_confirmation_email.delay')
    def test_includes_booked_ranges_per_room(self, mock_delay):
        self.client.post('/api/hotels/bookings/', {
            'room_id': str(self.room1.pk), 'start_date': '2027-01-01', 'end_date': '2027-01-03',
            'guest_name': 'Gu', 'guest_email': 'gu@example.com',
        })
        self.client.force_authenticate(user=self.owner)
        resp = self.client.get('/api/hotels/rooms/calendar/')
        room1_data = next(r for r in resp.data['rooms'] if r['room_id'] == str(self.room1.pk))
        self.assertEqual(len(room1_data['booked_ranges']), 1)
        room2_data = next(r for r in resp.data['rooms'] if r['room_id'] == str(self.room2.pk))
        self.assertEqual(room2_data['booked_ranges'], [])

    def test_invalid_from_date(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.get('/api/hotels/rooms/calendar/?from=not-a-date')
        self.assertEqual(resp.status_code, 400)

    def test_invalid_to_date(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.get('/api/hotels/rooms/calendar/?to=not-a-date')
        self.assertEqual(resp.status_code, 400)

    @patch('notifications.tasks.send_booking_confirmation_email.delay')
    def test_from_to_window_filters_ranges(self, mock_delay):
        self.client.post('/api/hotels/bookings/', {
            'room_id': str(self.room1.pk), 'start_date': '2027-02-01', 'end_date': '2027-02-03',
            'guest_name': 'Gu', 'guest_email': 'gu@example.com',
        })
        self.client.force_authenticate(user=self.owner)
        # Window entirely after the booking -> excluded
        resp = self.client.get('/api/hotels/rooms/calendar/?from=2027-03-01&to=2027-03-05')
        room1_data = next(r for r in resp.data['rooms'] if r['room_id'] == str(self.room1.pk))
        self.assertEqual(room1_data['booked_ranges'], [])
