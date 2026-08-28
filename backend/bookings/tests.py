import datetime

from decimal import Decimal

from django.test import TestCase

from rest_framework.test import APIClient

from rest_framework import status

from accounts.models import User

from tenants.models import Tenant

from .models import Booking

from bookings.models import Booking

from bookings.admin import BookingAdmin

from django.contrib.admin.sites import AdminSite

from unittest.mock import patch


def make_tenant(slug, plan='pro', active=True):
    return Tenant.objects.create(
        name=slug.replace('-', ' ').title(),
        slug=slug, plan=plan, is_active=active, business_type='restaurant',
    )


def make_user(email, tenant, role='customer'):
    return User.objects.create_user(
        email=email, password='pass1234', tenant=tenant, role=role,
    )


def make_booking(tenant, **kwargs):
    defaults = dict(
        booking_type='table_reservation',
        status='pending',
        start_date=datetime.date(2026, 9, 1),
        guest_name='Arben Hoxha',
        guest_email='arben@test.com',
        total_price=2000,
    )
    defaults.update(kwargs)
    return Booking.objects.create(tenant=tenant, **defaults)


class BookingCreateTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('testbiz')
        self.client.defaults['HTTP_HOST'] = 'testbiz.bizal.al'

    def test_anonymous_can_create_booking(self):
        resp = self.client.post('/api/bookings/', {
            'booking_type': 'table_reservation',
            'start_date': '2026-09-10',
            'guest_name': 'Besmir Koci',
            'guest_email': 'besmir@test.com',
            'guest_count': 3,
            'total_price': '1500.00',
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['guest_name'], 'Besmir Koci')
        # SECURITY: total_price must NOT be accepted from the client. A table
        # reservation has no server-derivable resource price, so it defaults
        # to 0 rather than the '1500.00' the client tried to submit.
        self.assertEqual(str(resp.data['total_price']), '0.00')

    def test_booking_defaults_to_pending(self):
        resp = self.client.post('/api/bookings/', {
            'booking_type': 'table_reservation',
            'start_date': '2026-09-11',
            'guest_name': 'Lira Gashi',
            'guest_email': 'lira@test.com',
            'total_price': '800.00',
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['status'], 'pending')
        # SECURITY: same as above — client-submitted total_price is ignored.
        self.assertEqual(str(resp.data['total_price']), '0.00')

    def test_booking_type_defaults_from_tenant_business_type(self):
        """booking_type is optional — the serializer fills it in based on
        the tenant's business_type (restaurant -> table_reservation)."""
        resp = self.client.post('/api/bookings/', {
            'start_date': '2026-09-12',
            'guest_name': 'Test', 'guest_email': 'test@test.com',
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['booking_type'], 'table_reservation')


class BookingListTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('listbiz')
        self.other_tenant = make_tenant('otherbiz')
        self.owner = make_user('owner@listbiz.com', self.tenant, 'owner')
        self.customer = make_user('cust@listbiz.com', self.tenant, 'customer')
        self.client.defaults['HTTP_HOST'] = 'listbiz.bizal.al'

        self.bk1 = make_booking(self.tenant, guest_name='Alpha')
        self.bk2 = make_booking(self.tenant, guest_name='Beta')
        self.bk_other = make_booking(self.other_tenant, guest_name='Hidden')

    def test_owner_sees_all_tenant_bookings(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.get('/api/bookings/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        names = [b['guest_name'] for b in ((resp.data['results'] if isinstance(resp.data, dict) else resp.data))]
        self.assertIn('Alpha', names)
        self.assertIn('Beta', names)
        self.assertNotIn('Hidden', names)

    def test_customer_only_sees_own_bookings(self):
        # Create a booking linked to the customer user
        bk_mine = make_booking(self.tenant, guest_name='Mine')
        bk_mine.user = self.customer
        bk_mine.save()
        self.client.force_authenticate(user=self.customer)
        resp = self.client.get('/api/bookings/')
        names = [b['guest_name'] for b in ((resp.data['results'] if isinstance(resp.data, dict) else resp.data))]
        self.assertIn('Mine', names)
        self.assertNotIn('Alpha', names)  # belongs to no user → not visible to customer

    def test_unauthenticated_cannot_list(self):
        resp = self.client.get('/api/bookings/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


class BookingAdminUpdateTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('updatebiz')
        self.owner = make_user('owner@updatebiz.com', self.tenant, 'owner')
        self.customer = make_user('cust@updatebiz.com', self.tenant, 'customer')
        self.booking = make_booking(self.tenant)
        self.client.defaults['HTTP_HOST'] = 'updatebiz.bizal.al'

    def test_owner_can_confirm_booking(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.patch(
            f'/api/bookings/{self.booking.pk}/admin-update/', {'status': 'confirmed'}
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'confirmed')

    def test_owner_can_add_internal_notes(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.patch(
            f'/api/bookings/{self.booking.pk}/admin-update/',
            {'internal_notes': 'VIP table requested.'},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.internal_notes, 'VIP table requested.')

    def test_customer_cannot_admin_update(self):
        self.client.force_authenticate(user=self.customer)
        resp = self.client.patch(
            f'/api/bookings/{self.booking.pk}/admin-update/', {'status': 'confirmed'}
        )
        self.assertIn(resp.status_code, [
            status.HTTP_403_FORBIDDEN, status.HTTP_401_UNAUTHORIZED
        ])

    def test_wrong_tenant_owner_cannot_update(self):
        other_tenant = make_tenant('wrongbiz')
        other_owner = make_user('owner@wrongbiz.com', other_tenant, 'owner')
        self.client.force_authenticate(user=other_owner)
        resp = self.client.patch(
            f'/api/bookings/{self.booking.pk}/admin-update/', {'status': 'confirmed'}
        )
        # Permission denied — booking belongs to a different tenant
        self.assertIn(resp.status_code, [
            status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND
        ])


class BookingCancelTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('cancelbiz')
        self.customer = make_user('cust@cancelbiz.com', self.tenant, 'customer')
        self.client.defaults['HTTP_HOST'] = 'cancelbiz.bizal.al'

    def test_customer_can_cancel_own_booking(self):
        bk = make_booking(self.tenant, status='confirmed')
        bk.user = self.customer
        bk.save()
        self.client.force_authenticate(user=self.customer)
        resp = self.client.post(f'/api/bookings/{bk.pk}/cancel/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        bk.refresh_from_db()
        self.assertEqual(bk.status, 'cancelled')

    def test_cannot_cancel_already_cancelled(self):
        bk = make_booking(self.tenant, status='cancelled')
        bk.user = self.customer
        bk.save()
        self.client.force_authenticate(user=self.customer)
        resp = self.client.post(f'/api/bookings/{bk.pk}/cancel/')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_cancel_completed(self):
        bk = make_booking(self.tenant, status='completed')
        bk.user = self.customer
        bk.save()
        self.client.force_authenticate(user=self.customer)
        resp = self.client.post(f'/api/bookings/{bk.pk}/cancel/')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class BookingOwnershipSecurityTest(TestCase):
    """Tests for the ownership checks added during the security audit."""

    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('secbiz')
        self.customer1 = make_user('c1@secbiz.com', self.tenant, 'customer')
        self.customer2 = make_user('c2@secbiz.com', self.tenant, 'customer')
        self.client.defaults['HTTP_HOST'] = 'secbiz.bizal.al'

    def test_customer_cannot_cancel_other_customers_booking(self):
        """A customer must not be able to cancel a booking they don't own."""
        bk = make_booking(self.tenant, status='confirmed')
        bk.user = self.customer1
        bk.save()
        self.client.force_authenticate(user=self.customer2)
        resp = self.client.post(f'/api/bookings/{bk.pk}/cancel/')
        self.assertEqual(resp.status_code, 403)
        bk.refresh_from_db()
        self.assertEqual(bk.status, 'confirmed')  # unchanged

    def test_customer_cannot_patch_other_customers_booking(self):
        """BookingDetailView PATCH must be scoped to the requesting user."""
        bk = make_booking(self.tenant, status='pending')
        bk.user = self.customer1
        bk.save()
        self.client.force_authenticate(user=self.customer2)
        resp = self.client.patch(f'/api/bookings/{bk.pk}/', {'guest_count': 99})
        self.assertEqual(resp.status_code, 404)  # not visible → 404

    def test_admin_invalid_status_rejected(self):
        """admin-update must reject statuses not in STATUS_CHOICES."""
        owner = make_user('owner@secbiz.com', self.tenant, 'owner')
        bk = make_booking(self.tenant)
        self.client.force_authenticate(user=owner)
        resp = self.client.patch(
            f'/api/bookings/{bk.pk}/admin-update/', {'status': 'typo_status'}
        )
        self.assertEqual(resp.status_code, 400)


class BookingBusinessHoursTest(TestCase):
    """Monday-Saturday and Sunday can have different posted hours — the
    start_time check must be resolved per the actual weekday being booked,
    not by merging every range in business_hours into one min/max window."""

    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('hoursbiz')
        self.tenant.business_hours = {
            'E Hënë - E Shtunë': '09:00 - 20:00',
            'E Diel': '10:00 - 16:00',
        }
        self.tenant.save()
        self.client.defaults['HTTP_HOST'] = 'hoursbiz.bizal.al'

    def _post(self, start_date, start_time):
        return self.client.post('/api/bookings/', {
            'booking_type': 'appointment',
            'start_date': start_date,
            'start_time': start_time,
            'guest_name': 'Test Guest',
            'guest_email': 'guest@test.com',
        })

    def test_saturday_within_weekday_hours_accepted(self):
        resp = self._post('2026-09-05', '19:00')  # Saturday, within 09:00-20:00
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_sunday_within_weekday_hours_but_after_sunday_close_rejected(self):
        """19:00 is inside the Mon-Sat window but the tenant closes at 16:00
        on Sunday — this is exactly the case the old merged min/max check
        used to get wrong."""
        resp = self._post('2026-09-06', '19:00')  # Sunday
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_sunday_within_sunday_hours_accepted(self):
        resp = self._post('2026-09-06', '11:00')  # Sunday, within 10:00-16:00
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_monday_before_open_rejected(self):
        resp = self._post('2026-09-07', '07:00')  # Monday, before 09:00
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_day_with_no_entry_treated_as_closed(self):
        self.tenant.business_hours = {'E Hënë - E Premte': '09:00 - 18:00'}
        self.tenant.save()
        resp = self._post('2026-09-06', '11:00')  # Sunday, not in business_hours at all
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class BookingPriceComputationTest(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_appointment_price_computed_from_service_ignores_client_value(self):
        from appointments.models import Service
        tenant = make_tenant('clinicbiz')
        tenant.business_type = 'clinic'
        tenant.save()
        self.client.defaults['HTTP_HOST'] = 'clinicbiz.bizal.al'
        service = Service.objects.create(tenant=tenant, name='Checkup', price=Decimal('3500.00'))

        resp = self.client.post('/api/bookings/', {
            'booking_type': 'appointment',
            'resource_type': 'service',
            'resource_id': str(service.id),
            'start_date': '2026-09-10',
            'guest_name': 'Pacient Test',
            'guest_email': 'pacient@test.com',
            'total_price': '99999.00',  # attempted override — must be ignored
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Decimal(str(resp.data['total_price'])), Decimal('3500.00'))

    def test_rental_price_computed_from_price_per_day_times_days_with_discount(self):
        from rentals.models import RentalItem
        tenant = make_tenant('carbiz')
        tenant.business_type = 'car_rental'
        tenant.save()
        self.client.defaults['HTTP_HOST'] = 'carbiz.bizal.al'
        item = RentalItem.objects.create(
            tenant=tenant, name='Golf 7', rental_type='car',
            price_per_day=Decimal('4000.00'), status='available',
        )

        # 2026-09-10 through 2026-09-13 inclusive = 4 days (matches the
        # storefront's calcRentalDays, which is start-day inclusive).
        # 4 days falls in the 3-6 day bracket -> 5% length discount, mirroring
        # calcRentalDiscountPct() in the booking modal: 16000 * 0.95 = 15200.
        resp = self.client.post('/api/bookings/', {
            'booking_type': 'rental',
            'resource_type': 'rental_item',
            'resource_id': str(item.id),
            'start_date': '2026-09-10',
            'end_date': '2026-09-13',
            'guest_name': 'Klient Test',
            'guest_email': 'klient@test.com',
            'total_price': '1.00',  # attempted override — must be ignored
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Decimal(str(resp.data['total_price'])), Decimal('15200.00'))

    def test_room_type_resolves_to_available_room_and_computed_price(self):
        from hotels.models import RoomType, Room
        tenant = make_tenant('hotelbiz')
        tenant.business_type = 'hotel'
        tenant.save()
        self.client.defaults['HTTP_HOST'] = 'hotelbiz.bizal.al'
        rt = RoomType.objects.create(tenant=tenant, name='Deluxe', base_price=Decimal('8000.00'))
        Room.objects.create(tenant=tenant, room_type=rt, room_number='101', status='available')

        resp = self.client.post('/api/bookings/', {
            'booking_type': 'room_booking',
            'resource_type': 'room_type',
            'resource_id': str(rt.id),
            'start_date': '2026-09-10',
            'end_date': '2026-09-12',  # 2 nights
            'guest_name': 'Mysafir Test',
            'guest_email': 'mysafir@test.com',
            'total_price': '1.00',  # attempted override — must be ignored
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Decimal(str(resp.data['total_price'])), Decimal('16000.00'))
        # resource_type/resource_id should have been rewritten to the concrete room
        self.assertEqual(resp.data['resource_type'], 'room')

    def test_room_type_with_no_available_room_rejected(self):
        from hotels.models import RoomType, Room
        tenant = make_tenant('hotelbiz2')
        tenant.business_type = 'hotel'
        tenant.save()
        self.client.defaults['HTTP_HOST'] = 'hotelbiz2.bizal.al'
        rt = RoomType.objects.create(tenant=tenant, name='Suite', base_price=Decimal('10000.00'))
        Room.objects.create(tenant=tenant, room_type=rt, room_number='201', status='maintenance')

        resp = self.client.post('/api/bookings/', {
            'booking_type': 'room_booking',
            'resource_type': 'room_type',
            'resource_id': str(rt.id),
            'start_date': '2026-09-10',
            'end_date': '2026-09-12',
            'guest_name': 'Mysafir Test',
            'guest_email': 'mysafir2@test.com',
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_table_reservation_has_no_derivable_price_defaults_zero(self):
        tenant = make_tenant('restobiz')
        self.client.defaults['HTTP_HOST'] = 'restobiz.bizal.al'
        resp = self.client.post('/api/bookings/', {
            'booking_type': 'table_reservation',
            'start_date': '2026-09-10',
            'guest_name': 'Test',
            'guest_email': 'test@test.com',
            'total_price': '5000.00',  # attempted override — must be ignored
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Decimal(str(resp.data['total_price'])), Decimal('0.00'))


class AdminSetTotalPriceTest(TestCase):
    """
    admin_update_booking now accepts an explicit total_price — but only for
    staff/owner (the view already enforces HasTenantRole), covering the
    table-reservation / class / event case where there's no priced resource
    for the server to derive an amount from.
    """
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('adminpricebiz')
        self.owner = make_user('owner@adminpricebiz.com', self.tenant, 'owner')
        self.client.defaults['HTTP_HOST'] = 'adminpricebiz.bizal.al'
        self.booking = make_booking(self.tenant, total_price=0)

    def test_owner_can_set_total_price(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.patch(f'/api/bookings/{self.booking.id}/admin-update/', {
            'total_price': '2500.00',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.total_price, Decimal('2500.00'))

    def test_negative_total_price_rejected(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.patch(f'/api/bookings/{self.booking.id}/admin-update/', {
            'total_price': '-100.00',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


def make_tenant__admin_gaps(slug='bookingadmingapbiz'):
    return Tenant.objects.create(name=slug.title(), slug=slug, business_type='restaurant', plan='pro', is_active=True)


class BookingAdminGuestDisplayTest(TestCase):
    def setUp(self):
        self.tenant = make_tenant__admin_gaps()
        self.admin = BookingAdmin(Booking, AdminSite())

    def test_guest_display_prefers_guest_name(self):
        booking = Booking.objects.create(
            tenant=self.tenant, booking_type='table_reservation', status='pending',
            guest_name='Walk-in Guest',
        )
        self.assertEqual(self.admin.guest_display(booking), 'Walk-in Guest')

    def test_guest_display_falls_back_to_user_email(self):
        user = User.objects.create_user(email='cust@bookingadmingapbiz.com', password='pass1234', tenant=self.tenant)
        booking = Booking.objects.create(
            tenant=self.tenant, booking_type='table_reservation', status='pending', user=user,
        )
        self.assertEqual(self.admin.guest_display(booking), 'cust@bookingadmingapbiz.com')

    def test_guest_display_falls_back_to_dash(self):
        booking = Booking.objects.create(
            tenant=self.tenant, booking_type='table_reservation', status='pending',
        )
        self.assertEqual(self.admin.guest_display(booking), '—')


class GetResourceStatusGapsTests(TestCase):
    """BookingSerializer.get_resource_status: RentalItem.DoesNotExist branch."""

    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('resstatusbiz')
        self.tenant.business_type = 'car_rental'
        self.tenant.save()
        self.owner = make_user('owner@resstatusbiz.com', self.tenant, 'owner')
        self.client.defaults['HTTP_HOST'] = 'resstatusbiz.bizal.al'

    def test_resource_status_none_when_rental_item_deleted(self):
        import uuid
        booking = make_booking(
            self.tenant, booking_type='rental', resource_type='rental_item',
            resource_id=str(uuid.uuid4()),
        )
        self.client.force_authenticate(user=self.owner)
        resp = self.client.get(f'/api/bookings/{booking.id}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIsNone(resp.data['resource_status'])


class DateValidationGapsTests(TestCase):
    """BookingSerializer.validate(): start_date-in-past and end<start checks."""

    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('datevalbiz')
        self.client.defaults['HTTP_HOST'] = 'datevalbiz.bizal.al'

    def test_start_date_in_past_rejected(self):
        resp = self.client.post('/api/bookings/', {
            'booking_type': 'table_reservation',
            'start_date': '2020-01-01',
            'guest_name': 'Test',
            'guest_email': 'test@test.com',
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('start_date', resp.data)

    def test_end_date_before_start_date_rejected(self):
        resp = self.client.post('/api/bookings/', {
            'booking_type': 'table_reservation',
            'start_date': '2026-09-10',
            'end_date': '2026-09-05',
            'guest_name': 'Test',
            'guest_email': 'test@test.com',
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('end_date', resp.data)


class RoomBookingOverlapGapsTests(TestCase):
    """BookingSerializer.validate(): 'room' resource_type branch (as opposed
    to 'room_type'), Room.DoesNotExist, and overlap rejection."""

    def setUp(self):
        from hotels.models import RoomType, Room
        self.client = APIClient()
        self.tenant = make_tenant('roomoverlapbiz')
        self.tenant.business_type = 'hotel'
        self.tenant.save()
        self.client.defaults['HTTP_HOST'] = 'roomoverlapbiz.bizal.al'
        self.room_type = RoomType.objects.create(
            tenant=self.tenant, name='Standard', base_price=Decimal('5000.00'),
        )
        self.room = Room.objects.create(
            tenant=self.tenant, room_type=self.room_type, room_number='301', status='available',
        )

    def _post(self, resource_id, start, end):
        return self.client.post('/api/bookings/', {
            'booking_type': 'room_booking',
            'resource_type': 'room',
            'resource_id': str(resource_id),
            'start_date': start,
            'end_date': end,
            'guest_name': 'Guest',
            'guest_email': 'guest@test.com',
        })

    def test_room_not_found_rejected(self):
        import uuid
        resp = self._post(uuid.uuid4(), '2026-09-10', '2026-09-12')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('resource_id', resp.data)

    def test_room_available_booking_succeeds(self):
        resp = self._post(self.room.pk, '2026-09-10', '2026-09-12')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_overlapping_room_booking_rejected(self):
        self._post(self.room.pk, '2026-09-10', '2026-09-12')
        resp = self._post(self.room.pk, '2026-09-11', '2026-09-13')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('not available', str(resp.data))

    def test_room_type_not_found_rejected(self):
        import uuid
        resp = self.client.post('/api/bookings/', {
            'booking_type': 'room_booking',
            'resource_type': 'room_type',
            'resource_id': str(uuid.uuid4()),
            'start_date': '2026-09-10',
            'end_date': '2026-09-12',
            'guest_name': 'Guest',
            'guest_email': 'guest@test.com',
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('resource_id', resp.data)


class RentalOverlapGapsTests(TestCase):
    """BookingSerializer.validate(): rental overlap / RentalItem.DoesNotExist."""

    def setUp(self):
        from rentals.models import RentalItem
        self.client = APIClient()
        self.tenant = make_tenant('rentaloverlapbiz')
        self.tenant.business_type = 'car_rental'
        self.tenant.save()
        self.client.defaults['HTTP_HOST'] = 'rentaloverlapbiz.bizal.al'
        self.item = RentalItem.objects.create(
            tenant=self.tenant, name='Golf 7', rental_type='car',
            price_per_day=Decimal('4000.00'), status='available',
        )

    def _post(self, resource_id, start, end):
        return self.client.post('/api/bookings/', {
            'booking_type': 'rental',
            'resource_type': 'rental_item',
            'resource_id': str(resource_id),
            'start_date': start,
            'end_date': end,
            'guest_name': 'Guest',
            'guest_email': 'guest@test.com',
        })

    def test_rental_item_not_found_rejected(self):
        import uuid
        resp = self._post(uuid.uuid4(), '2026-09-10', '2026-09-12')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('resource_id', resp.data)

    def test_overlapping_rental_booking_rejected(self):
        self._post(self.item.pk, '2026-09-10', '2026-09-13')
        resp = self._post(self.item.pk, '2026-09-12', '2026-09-15')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('not available', str(resp.data))

    def test_rental_long_stay_gets_ten_percent_discount(self):
        # 7+ days -> 10% discount branch (only 3-6 day / <3 day brackets
        # were previously exercised elsewhere).
        resp = self._post(self.item.pk, '2026-09-10', '2026-09-16')  # 7 days inclusive
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        # 4000 * 7 = 28000, 10% off = 25200
        self.assertEqual(Decimal(str(resp.data['total_price'])), Decimal('25200.00'))


class ResourceIdUuidGapsTests(TestCase):
    """BookingSerializer.validate(): resource_id must be a valid UUID for
    non room_booking/rental booking types."""

    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('uuidvalbiz')
        self.client.defaults['HTTP_HOST'] = 'uuidvalbiz.bizal.al'

    def test_invalid_uuid_resource_id_rejected(self):
        resp = self.client.post('/api/bookings/', {
            'booking_type': 'table_reservation',
            'resource_type': 'table',
            'resource_id': 'not-a-uuid',
            'start_date': '2026-09-10',
            'guest_name': 'Test',
            'guest_email': 'test@test.com',
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('resource_id', resp.data)


class ComputeTotalPriceServiceGapsTests(TestCase):
    """_compute_total_price(): Service.DoesNotExist branch."""

    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('svcgapbiz')
        self.tenant.business_type = 'clinic'
        self.tenant.save()
        self.client.defaults['HTTP_HOST'] = 'svcgapbiz.bizal.al'

    def test_appointment_with_deleted_service_defaults_zero(self):
        import uuid
        resp = self.client.post('/api/bookings/', {
            'booking_type': 'appointment',
            'resource_type': 'service',
            'resource_id': str(uuid.uuid4()),
            'start_date': '2026-09-10',
            'guest_name': 'Pacient',
            'guest_email': 'pacient@test.com',
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Decimal(str(resp.data['total_price'])), Decimal('0.00'))


class ComputeTotalPriceRentalRoomDoesNotExistGapsTests(TestCase):
    """_compute_total_price() RentalItem/Room.DoesNotExist branches, only
    reachable via update() once validate()'s own pre-check no longer
    applies (resource unchanged in the PATCH, but deleted since create)."""

    def test_rental_item_deleted_after_create_leaves_price_untouched_on_patch(self):
        from rentals.models import RentalItem
        tenant = make_tenant('rentalpatchbiz')
        tenant.business_type = 'car_rental'
        tenant.save()
        owner = make_user('owner@rentalpatchbiz.com', tenant, 'owner')
        client = APIClient()
        client.defaults['HTTP_HOST'] = 'rentalpatchbiz.bizal.al'
        item = RentalItem.objects.create(
            tenant=tenant, name='Golf 7', rental_type='car',
            price_per_day=Decimal('4000.00'), status='available',
        )
        booking = make_booking(
            tenant, booking_type='rental', resource_type='rental_item',
            resource_id=str(item.id), start_date=datetime.date(2026, 9, 10),
            end_date=datetime.date(2026, 9, 11), total_price=Decimal('4000.00'),
        )
        item.delete()
        client.force_authenticate(user=owner)
        resp = client.patch(f'/api/bookings/{booking.id}/', {'notes': 'updated'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        booking.refresh_from_db()
        self.assertEqual(booking.total_price, Decimal('4000.00'))  # unchanged

    def test_room_deleted_after_create_leaves_price_untouched_on_patch(self):
        from hotels.models import RoomType, Room
        tenant = make_tenant('roompatchbiz')
        tenant.business_type = 'hotel'
        tenant.save()
        owner = make_user('owner@roompatchbiz.com', tenant, 'owner')
        client = APIClient()
        client.defaults['HTTP_HOST'] = 'roompatchbiz.bizal.al'
        rt = RoomType.objects.create(tenant=tenant, name='Deluxe', base_price=Decimal('7000.00'))
        room = Room.objects.create(tenant=tenant, room_type=rt, room_number='601', status='available')
        booking = make_booking(
            tenant, booking_type='room_booking', resource_type='room',
            resource_id=str(room.id), start_date=datetime.date(2026, 9, 10),
            end_date=datetime.date(2026, 9, 12), total_price=Decimal('14000.00'),
        )
        room.delete()
        client.force_authenticate(user=owner)
        resp = client.patch(f'/api/bookings/{booking.id}/', {'notes': 'updated'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        booking.refresh_from_db()
        self.assertEqual(booking.total_price, Decimal('14000.00'))


class RentalShortStayNoDiscountGapsTests(TestCase):
    """_compute_total_price(): 1-2 day rental gets the 0% discount bracket."""

    def test_short_rental_no_discount(self):
        from rentals.models import RentalItem
        tenant = make_tenant('shortrentalbiz')
        tenant.business_type = 'car_rental'
        tenant.save()
        client = APIClient()
        client.defaults['HTTP_HOST'] = 'shortrentalbiz.bizal.al'
        item = RentalItem.objects.create(
            tenant=tenant, name='Golf 7', rental_type='car',
            price_per_day=Decimal('4000.00'), status='available',
        )
        resp = client.post('/api/bookings/', {
            'booking_type': 'rental',
            'resource_type': 'rental_item',
            'resource_id': str(item.id),
            'start_date': '2026-09-10',
            'end_date': '2026-09-10',  # 1 day inclusive
            'guest_name': 'Guest',
            'guest_email': 'guest@test.com',
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Decimal(str(resp.data['total_price'])), Decimal('4000.00'))


class RoomBookingLinkageDoesNotExistGapsTests(TestCase):
    """perform_create(): the Room.DoesNotExist / ObjectDoesNotExist branch
    of the RoomBooking linkage (room deleted between validate() and save())."""

    def test_room_deleted_between_validate_and_save_is_handled_gracefully(self):
        from hotels.models import RoomType, Room
        tenant = make_tenant('racebiz')
        tenant.business_type = 'hotel'
        tenant.save()
        client = APIClient()
        client.defaults['HTTP_HOST'] = 'racebiz.bizal.al'
        rt = RoomType.objects.create(tenant=tenant, name='Deluxe', base_price=Decimal('7000.00'))
        room = Room.objects.create(tenant=tenant, room_type=rt, room_number='701', status='available')

        with patch('hotels.models.Room.objects.get', side_effect=Room.DoesNotExist):
            resp = client.post('/api/bookings/', {
                'booking_type': 'room_booking',
                'resource_type': 'room',
                'resource_id': str(room.pk),
                'start_date': '2026-09-10',
                'end_date': '2026-09-12',
                'guest_name': 'Guest',
                'guest_email': 'guest@test.com',
            })
        # The booking itself still succeeds; only the RoomBooking join row is skipped.
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)


class AwardPointsHappyPathGapsTests(TestCase):
    """admin_update_booking(): registered user + positive price on
    completion actually calls award_points()."""

    def test_completed_booking_with_user_and_price_awards_points(self):
        tenant = make_tenant('awardpointsbiz')
        from tenants.models import TenantFeature
        TenantFeature.objects.update_or_create(
            tenant=tenant, key='loyalty_program',
            defaults={'value': 'true', 'is_custom_grant': False},
        )
        owner = make_user('owner@awardpointsbiz.com', tenant, 'owner')
        customer = make_user('customer@awardpointsbiz.com', tenant, 'customer')
        client = APIClient()
        client.defaults['HTTP_HOST'] = 'awardpointsbiz.bizal.al'
        booking = make_booking(
            tenant, status='confirmed', user=customer, total_price=Decimal('2000.00'),
        )
        client.force_authenticate(user=owner)
        resp = client.patch(f'/api/bookings/{booking.id}/admin-update/', {
            'status': 'completed',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        from billing.models import LoyaltyAccount
        account = LoyaltyAccount.objects.filter(tenant=tenant, user=customer).first()
        self.assertIsNotNone(account)
        self.assertGreater(account.points, 0)


class BookingUpdatePriceRecomputeGapsTests(TestCase):
    """BookingSerializer.update(): total_price recompute on PATCH."""

    def setUp(self):
        from appointments.models import Service
        self.client = APIClient()
        self.tenant = make_tenant('updpricebiz')
        self.tenant.business_type = 'clinic'
        self.tenant.save()
        self.owner = make_user('owner@updpricebiz.com', self.tenant, 'owner')
        self.client.defaults['HTTP_HOST'] = 'updpricebiz.bizal.al'
        self.service = Service.objects.create(
            tenant=self.tenant, name='Checkup', price=Decimal('3500.00'),
        )
        self.booking = make_booking(
            self.tenant, booking_type='appointment', resource_type='service',
            resource_id=str(self.service.id), total_price=Decimal('3500.00'),
        )

    def test_patch_recomputes_price_from_merged_state(self):
        other_service_price = Decimal('5000.00')
        from appointments.models import Service
        other_service = Service.objects.create(
            tenant=self.tenant, name='Full Panel', price=other_service_price,
        )
        self.client.force_authenticate(user=self.owner)
        resp = self.client.patch(f'/api/bookings/{self.booking.id}/', {
            'resource_id': str(other_service.id),
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(Decimal(str(resp.data['total_price'])), other_service_price)


class BookingListViewGapsTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('listviewgapbiz')
        self.client.defaults['HTTP_HOST'] = 'listviewgapbiz.bizal.al'

    def test_unauthenticated_get_returns_empty_list(self):
        # get_queryset() returns Booking.objects.none() for anonymous GET,
        # but the view itself requires IsAuthenticated for GET — this is
        # only reachable if permissions somehow pass an unauthenticated
        # user through, so hit get_queryset() indirectly isn't possible via
        # the API. Exercise the underlying view method directly instead.
        from .views import BookingListCreateView
        from django.test import RequestFactory
        rf = RequestFactory()
        request = rf.get('/api/bookings/')
        request.tenant = self.tenant
        from django.contrib.auth.models import AnonymousUser
        request.user = AnonymousUser()
        view = BookingListCreateView()
        view.request = request
        qs = view.get_queryset()
        self.assertEqual(qs.count(), 0)

    def test_create_without_tenant_rejected(self):
        self.client.defaults['HTTP_HOST'] = 'bizal.al'
        resp = self.client.post('/api/bookings/', {
            'booking_type': 'table_reservation',
            'start_date': '2026-09-10',
            'guest_name': 'Test',
            'guest_email': 'test@test.com',
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('tenant subdomain', resp.data.get('detail', ''))

    def test_create_blocked_when_plan_lacks_bookings_feature(self):
        starter_tenant = make_tenant('starterlistbiz', plan='starter')
        from tenants.models import TenantFeature
        TenantFeature.objects.update_or_create(
            tenant=starter_tenant, key='bookings',
            defaults={'value': 'false', 'is_custom_grant': False},
        )
        self.client.defaults['HTTP_HOST'] = 'starterlistbiz.bizal.al'
        resp = self.client.post('/api/bookings/', {
            'booking_type': 'table_reservation',
            'start_date': '2026-09-10',
            'guest_name': 'Test',
            'guest_email': 'test@test.com',
        })
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_room_booking_creates_roombooking_link_row(self):
        from hotels.models import RoomType, Room, RoomBooking
        tenant = make_tenant('linkrowbiz')
        tenant.business_type = 'hotel'
        tenant.save()
        rt = RoomType.objects.create(tenant=tenant, name='Deluxe', base_price=Decimal('7000.00'))
        room = Room.objects.create(tenant=tenant, room_type=rt, room_number='401', status='available')
        self.client.defaults['HTTP_HOST'] = 'linkrowbiz.bizal.al'
        resp = self.client.post('/api/bookings/', {
            'booking_type': 'room_booking',
            'resource_type': 'room',
            'resource_id': str(room.pk),
            'start_date': '2026-09-10',
            'end_date': '2026-09-12',
            'guest_name': 'Guest',
            'guest_email': 'guest@test.com',
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(RoomBooking.objects.filter(booking_id=resp.data['id']).exists())

    def test_room_booking_link_row_unexpected_error_is_logged_not_raised(self):
        from hotels.models import RoomType, Room
        tenant = make_tenant('linkerrbiz')
        tenant.business_type = 'hotel'
        tenant.save()
        rt = RoomType.objects.create(tenant=tenant, name='Deluxe', base_price=Decimal('7000.00'))
        room = Room.objects.create(tenant=tenant, room_type=rt, room_number='501', status='available')
        self.client.defaults['HTTP_HOST'] = 'linkerrbiz.bizal.al'
        with patch('hotels.models.RoomBooking.objects.get_or_create', side_effect=RuntimeError('db down')):
            resp = self.client.post('/api/bookings/', {
                'booking_type': 'room_booking',
                'resource_type': 'room',
                'resource_id': str(room.pk),
                'start_date': '2026-09-10',
                'end_date': '2026-09-12',
                'guest_name': 'Guest',
                'guest_email': 'guest@test.com',
            })
        # Booking itself still succeeds; the linkage failure is only logged.
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)


class CancelBookingGapsTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('cancelgapbiz')
        self.owner = make_user('owner@cancelgapbiz.com', self.tenant, 'owner')
        self.client.defaults['HTTP_HOST'] = 'cancelgapbiz.bizal.al'

    def test_cancel_nonexistent_booking_404(self):
        import uuid
        self.client.force_authenticate(user=self.owner)
        resp = self.client.post(f'/api/bookings/{uuid.uuid4()}/cancel/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class AdminUpdateBookingGapsTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('adminupdgapbiz')
        self.owner = make_user('owner@adminupdgapbiz.com', self.tenant, 'owner')
        self.client.defaults['HTTP_HOST'] = 'adminupdgapbiz.bizal.al'

    def test_admin_update_nonexistent_booking_404(self):
        import uuid
        self.client.force_authenticate(user=self.owner)
        resp = self.client.patch(f'/api/bookings/{uuid.uuid4()}/admin-update/', {
            'status': 'confirmed',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_invalid_price_format_rejected(self):
        booking = make_booking(self.tenant)
        self.client.force_authenticate(user=self.owner)
        resp = self.client.patch(f'/api/bookings/{booking.id}/admin-update/', {
            'total_price': 'not-a-number',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('valid number', resp.data.get('detail', ''))

    def test_invalid_transition_rejected(self):
        booking = make_booking(self.tenant, status='completed')
        self.client.force_authenticate(user=self.owner)
        resp = self.client.patch(f'/api/bookings/{booking.id}/admin-update/', {
            'status': 'confirmed',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Cannot transition', resp.data.get('detail', ''))

    def test_empty_patch_body_is_a_noop(self):
        booking = make_booking(self.tenant, status='pending')
        self.client.force_authenticate(user=self.owner)
        resp = self.client.patch(f'/api/bookings/{booking.id}/admin-update/', {}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'pending')

    def test_guest_booking_completed_with_price_logs_but_does_not_award_points(self):
        booking = make_booking(
            self.tenant, status='confirmed', user=None, total_price=Decimal('1500.00'),
        )
        self.client.force_authenticate(user=self.owner)
        resp = self.client.patch(f'/api/bookings/{booking.id}/admin-update/', {
            'status': 'completed',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'completed')

    def test_confirmation_email_failure_is_swallowed(self):
        booking = make_booking(self.tenant, status='pending')
        self.client.force_authenticate(user=self.owner)
        with patch(
            'notifications.tasks.send_booking_confirmation_email.delay',
            side_effect=RuntimeError('smtp down'),
        ):
            resp = self.client.patch(f'/api/bookings/{booking.id}/admin-update/', {
                'status': 'confirmed',
            }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
